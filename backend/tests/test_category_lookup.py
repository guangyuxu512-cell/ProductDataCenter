"""Contract tests for the two read-only platform calls and authorization."""
import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_application
from app.modules.category_lookup.api import get_central, get_lookup
from app.modules.category_lookup.client import DouyinCategoryClient, LookupError, normalize_candidates, normalize_fields
from app.modules.central.client import CentralCookie, CentralShop, CentralShopSession

PRODUCT_KEY = "synthetic-product-token-1234567890"
RPA_KEY = "synthetic-rpa-token-1234567890"
SIGNER_KEY = "synthetic-signer-token-1234567890"
COOKIE = "synthetic-session-value-never-expose"


@pytest.fixture
def settings(tmp_path):
    key = tmp_path / "signer"
    key.write_text(SIGNER_KEY)
    return Settings(_env_file=None, douyin_category_lookup_enabled=True,
                    douyin_signer_key_file=key, api_token=PRODUCT_KEY, rpa_api_token=RPA_KEY)


def make_session(shop_id=None):
    return CentralShopSession(shop_id=shop_id or uuid4(), platform="douyin", session_version=1,
                              cookies=(CentralCookie(name="sessionid", value=COOKIE, domain=".jinritemai.com"),
                                       CentralCookie(name="bad", value="dont-send", domain="other.example")))


def test_signed_search_and_schema_do_not_require_token_and_return_safe_fields(settings):
    calls = []
    def handler(request):
        if request.url.host == "product-cloud-signer-v1-product-signer-1":
            data = json.loads(request.content)
            assert request.headers["x-api-key"] == SIGNER_KEY
            assert data["aid"] == 4272 and "__token" not in data["full_url"]
            assert COOKIE in data["cookie"] and "dont-send" not in data["cookie"]
            if "msToken=" in data["full_url"]:
                assert data["ms_token"] == "generated"
            calls.append(("sign", data["method"], data["full_url"]))
            return httpx.Response(200, json={"ok": True, "a_bogus": "synthetic-signature", "msToken": "generated"})
        assert request.url.host == "fxg.jinritemai.com"
        assert request.url.params["a_bogus"] == "synthetic-signature"
        assert request.url.params["msToken"] == "generated"
        assert "__token" not in request.url.params and COOKIE in request.headers["cookie"]
        calls.append(("platform", request.method, request.url.path))
        if request.method == "GET":
            assert request.url.params["key"] == "勺子"
            return httpx.Response(200, json={"code": 0, "data": {"list": [
                {"category_id": 1000010075, "name": "汤勺", "path": "餐具 > 汤勺"}]}})
        body = json.loads(request.content)
        assert body["context"]["category_id"] == "1000010075" and "__token" not in body
        return httpx.Response(200, json={"code": 0, "data": {"model": {"category_properties": {"items": [
            {"id": 12, "label": "材质", "required": True, "options": [{"id": 3, "name": "不锈钢"}]},
            {"id": 13, "label": "隐藏", "hidden": True}]}}}})
    client = DouyinCategoryClient(settings, transport=httpx.MockTransport(handler))
    session = make_session()
    assert client.search(session, "勺子") == [{"id": "1000010075", "name": "汤勺", "path": "餐具 > 汤勺"}]
    assert client.schema(session, "1000010075", "不锈钢勺子") == [
        {"id": "12", "label": "材质", "required": True, "options": [{"label": "不锈钢", "value": "3"}]}]
    assert [item[0] for item in calls] == ["sign", "sign", "platform", "sign", "sign", "platform"]


def test_lookup_rejects_redirect_and_does_not_expose_sensitive_exception(settings):
    def handler(request):
        if request.url.host != "fxg.jinritemai.com":
            return httpx.Response(200, json={"ok": True, "a_bogus": "signature"})
        raise httpx.ConnectError(COOKIE + SIGNER_KEY, request=request)
    client = DouyinCategoryClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(LookupError) as error:
        client.search(make_session(), "勺子")
    assert str(error.value) == "platform_unavailable"
    assert COOKIE not in str(error.value) and SIGNER_KEY not in str(error.value)


def test_httpx_info_log_does_not_expose_signed_query(settings, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    def handler(request):
        if request.url.host != "fxg.jinritemai.com":
            return httpx.Response(200, json={"ok": True, "a_bogus": "fake-sensitive-signature", "msToken": "fake-sensitive-ms-token"})
        return httpx.Response(200, json={"code": 0, "data": []})
    DouyinCategoryClient(settings, transport=httpx.MockTransport(handler)).search(make_session(), "私人商品名称")
    assert "fake-sensitive-signature" not in caplog.text
    assert "fake-sensitive-ms-token" not in caplog.text
    assert "私人商品名称" not in caplog.text


def test_candidates_never_guess_unrelated_ids_or_return_raw_fields():
    payload = {"list": [{"category_list": [{"id": 10, "name": "餐具"}, {"id": 11, "name": "汤勺"}],
                         "secret": COOKIE}, {"category_id": 11, "name": "汤勺"}, {"name": "无 ID"}]}
    assert normalize_candidates(payload) == [{"id": "11", "name": "餐具 > 汤勺", "path": "餐具 > 汤勺"}]


def test_platform_level_names_and_integer_required_are_preserved():
    assert normalize_candidates({"list": [{"categoryLeafId": 11, "third_cname": "汤勺",
                                            "first_cname": "餐饮厨具", "second_cname": "餐具"}]}) == [
        {"id": "11", "name": "汤勺", "path": "餐饮厨具 > 餐具 > 汤勺"}]
    assert normalize_fields([{"id": 12, "label": "材质", "required": 1}])[0]["required"] is True


class FakeCentral:
    def __init__(self, ids):
        self.ids = ids
    def list_shops(self):
        return [CentralShop(shop_id=i, display_name="测试店", platform="douyin", session_status="valid") for i in self.ids]
    def read_session(self, shop_id, expected_platform):
        assert shop_id in self.ids and expected_platform == "douyin"
        return make_session(shop_id)


class FakeLookup:
    def __init__(self, settings):
        self.settings = settings
    def search(self, session, keyword):
        assert keyword == "勺子"
        return [{"id": "1000010075", "name": "汤勺", "path": "餐具 > 汤勺"}]
    def schema(self, session, category_id, title):
        return [{"id": "12", "label": "材质", "required": True, "options": []}]


def test_api_auto_assigns_shops_and_preserves_rpa_boundary(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    get_settings.cache_clear()
    ids = [uuid4(), uuid4()]
    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: FakeLookup(settings)
    with TestClient(app) as client:
        assert client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"}, headers={"Authorization": "Bearer " + RPA_KEY}).status_code == 401
        auth = {"Authorization": "Bearer " + PRODUCT_KEY}
        a = client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"}, headers=auth)
        b = client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"}, headers=auth)
        assert a.status_code == b.status_code == 200 and a.json()['shopId'] != b.json()['shopId']
        response = client.post('/api/v1/category-lookup/schema', json={"shopId": a.json()['shopId'], "categoryId": "1000010075", "title": "不锈钢勺子"}, headers=auth)
        assert response.status_code == 200 and response.json()['attributes'][0]['required']
        assert response.headers['cache-control'] == 'no-store' and COOKIE not in response.text
        denied = client.post('/api/v1/category-lookup/schema', json={"shopId": str(uuid4()), "categoryId": "1000010075"}, headers=auth)
        assert denied.status_code == 403
    get_settings.cache_clear()


def test_concurrent_products_are_evenly_distributed_and_bounded_per_shop(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    get_settings.cache_clear()
    ids = [uuid4() for _ in range(5)]
    lock, active, peak, assigned = Lock(), Counter(), Counter(), Counter()

    class TrackedLookup(FakeLookup):
        def search(self, session, keyword):
            with lock:
                assigned[session.shop_id] += 1
                active[session.shop_id] += 1
                peak[session.shop_id] = max(peak[session.shop_id], active[session.shop_id])
            sleep(0.02)
            with lock:
                active[session.shop_id] -= 1
            return super().search(session, keyword)

    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: TrackedLookup(settings)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=25) as pool:
        def query(_index):
            return client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"},
                               headers={"Authorization": "Bearer " + PRODUCT_KEY})
        responses = list(pool.map(query, range(25)))
    assert all(item.status_code == 200 for item in responses)
    assert sorted(assigned.values()) == [5, 5, 5, 5, 5]
    assert max(peak.values()) <= 3
    get_settings.cache_clear()
