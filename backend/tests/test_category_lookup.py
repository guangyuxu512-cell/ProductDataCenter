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
                                       CentralCookie(name="csrf_session_id", value="synthetic-csrf", domain=".jinritemai.com"),
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
        assert request.headers["x-secsdk-csrf-token"] == "synthetic-csrf"
        assert request.headers["x-tt-from-page"] == "https://fxg.jinritemai.com/ffa/g/create"
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


def test_search_reuses_session_ms_token_when_present(settings):
    session = make_session().model_copy(update={"cookies": (
        CentralCookie(name="sessionid", value=COOKIE, domain=".jinritemai.com"),
        CentralCookie(name="msToken", value="synthetic-ms-token", domain=".jinritemai.com"),
    )})
    calls = []
    def handler(request):
        if request.url.host != "fxg.jinritemai.com":
            data = json.loads(request.content)
            assert data["ms_token"] == "synthetic-ms-token"
            calls.append("sign")
            return httpx.Response(200, json={"ok": True, "a_bogus": "signature"})
        assert request.url.params["msToken"] == "synthetic-ms-token"
        calls.append("platform")
        return httpx.Response(200, json={"code": 0, "data": []})
    assert DouyinCategoryClient(settings, transport=httpx.MockTransport(handler)).search(session, "勺子") == []
    assert calls == ["sign", "platform"]


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


def test_original_category_schema_never_searches_and_retries_only_login_rejection(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    monkeypatch.setattr("app.modules.category_lookup.api._next", 0)
    get_settings.cache_clear()
    ids = sorted([uuid4(), uuid4()], key=str)
    attempted = []
    title = "完整商品标题" * 30

    class OriginalLookup(FakeLookup):
        def search(self, session, keyword):
            pytest.fail("原类目不应触发类目搜索")

        def schema(self, session, category_id, sent_title):
            attempted.append((session.shop_id, category_id, sent_title))
            if session.shop_id == ids[0]:
                raise LookupError("platform_rejected", 10008)
            return super().schema(session, category_id, sent_title)

    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: OriginalLookup(settings)
    with TestClient(app) as client:
        path = '/api/v1/category-lookup/schema/auto'
        auth = {"Authorization": "Bearer " + PRODUCT_KEY}
        assert client.post(path, json={"categoryId": "0"}, headers=auth).status_code == 422
        assert client.post(path, json={"categoryId": "1000010075"}, headers={"Authorization": "Bearer " + RPA_KEY}).status_code == 401
        response = client.post(path, json={"categoryId": "1000010075", "title": title}, headers=auth)
        assert response.status_code == 200
        assert response.json()['shopId'] == str(ids[1])
        assert response.json()['attributes'][0]['required']
        assert response.headers['cache-control'] == 'no-store' and COOKIE not in response.text
        assert attempted == [(ids[0], "1000010075", title), (ids[1], "1000010075", title)]
    get_settings.cache_clear()


def test_search_skips_only_product_session_rejection_and_uses_next_shop(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    monkeypatch.setattr("app.modules.category_lookup.api._next", 0)
    get_settings.cache_clear()
    ids = sorted([uuid4(), uuid4()], key=str)
    attempted = []

    class PartlyReadyLookup(FakeLookup):
        def search(self, session, keyword):
            attempted.append(session.shop_id)
            if session.shop_id == ids[0]:
                raise LookupError("platform_rejected", 10008)
            return super().search(session, keyword)

    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: PartlyReadyLookup(settings)
    with TestClient(app) as client:
        response = client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"},
                               headers={"Authorization": "Bearer " + PRODUCT_KEY})
    assert response.status_code == 200
    assert attempted == ids
    assert response.json()['shopId'] == str(ids[1])
    get_settings.cache_clear()


def test_search_stops_after_each_shop_once_and_does_not_retry_other_failures(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    monkeypatch.setattr("app.modules.category_lookup.api._next", 0)
    get_settings.cache_clear()
    ids = sorted([uuid4(), uuid4(), uuid4()], key=str)
    attempted = []

    class FailingLookup(FakeLookup):
        reason = "platform_rejected"
        code = 10008

        def search(self, session, keyword):
            attempted.append(session.shop_id)
            raise LookupError(self.reason, self.code)

    failure = FailingLookup(settings)
    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: failure
    with TestClient(app) as client:
        auth = {"Authorization": "Bearer " + PRODUCT_KEY}
        response = client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"}, headers=auth)
        assert response.status_code == 502
        assert "商品页会话未通过抖店验证" in response.json()['detail']
        assert attempted == ids
        attempted.clear()
        failure.reason, failure.code = "signer_unavailable", None
        response = client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"}, headers=auth)
        assert response.status_code == 502
        assert "签名服务不可用" in response.json()['detail']
        assert len(attempted) == 1
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
