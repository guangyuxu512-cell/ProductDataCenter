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
from app.modules.category_lookup import pure_signer
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
                    douyin_signer_mode="service", douyin_signer_key_file=key, category_cache_file=tmp_path / "categories.sqlite3",
                    api_token=PRODUCT_KEY, rpa_api_token=RPA_KEY)


def make_session(shop_id=None):
    return CentralShopSession(shop_id=shop_id or uuid4(), platform="douyin", session_version=1,
                              cookies=(CentralCookie(name="sessionid", value=COOKIE, domain=".jinritemai.com"),
                                       CentralCookie(name="csrf_session_id", value="synthetic-csrf", domain=".jinritemai.com"),
                                       CentralCookie(name="bad", value="dont-send", domain="other.example")))


def test_pure_signs_the_exact_utf8_body_sent_and_does_not_call_signer_service(settings, monkeypatch):
    pure_settings = settings.model_copy(update={"douyin_signer_mode": "pure", "douyin_signer_key_file": None})
    signed = []
    platform_requests = []

    def sign(query, user_agent, *, body, aid, page_id):
        signed.append((query, user_agent, body, aid, page_id))
        return "pure-signature"

    def handler(request):
        assert request.url.host == "fxg.jinritemai.com", "纯算不能请求原签名服务"
        assert request.url.params["a_bogus"] == "pure-signature"
        assert COOKIE in request.headers["cookie"]
        platform_requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"code": 0, "data": []})
        return httpx.Response(200, json={"code": 0, "data": {"model": {
            "category_properties": {"items": []}}}})

    monkeypatch.setattr(pure_signer, "generate", sign)
    client = DouyinCategoryClient(pure_settings, transport=httpx.MockTransport(handler))
    assert client.category_options(make_session(), "0") == []
    assert client.schema(make_session(), "1000010075", "不锈钢勺子") == []
    assert len(signed) == len(platform_requests) == 2
    for (query, user_agent, body, aid, page_id), request in zip(signed, platform_requests, strict=True):
        assert query == str(request.url.copy_remove_param("a_bogus")).split("?", 1)[1]
        assert body == request.content and user_agent == request.headers["user-agent"]
        assert (aid, page_id) == (4272, 6241)
    assert signed[0][2] == b"" and "不锈钢勺子" in signed[1][2].decode("utf-8")


def test_pure_body_hash_uses_wire_bytes_and_get_keeps_empty_body_hash():
    import hashlib

    def double_sm3(data):
        return hashlib.new("sm3", hashlib.new("sm3", data).digest()).digest()

    kwargs = {"aid": 4272, "page_id": 6241, "now_ms": 1793520000000,
              "enter_ms": 1793520000000, "rng": lambda: 0.2, "trace": True}
    body = '{"title":"不锈钢勺子"}'.encode("utf-8")
    post = pure_signer.generate("appid=1", "test-agent", body=body, **kwargs)
    get = pure_signer.generate("appid=1", "test-agent", **kwargs)
    assert bytes(post["body_hash"]) == double_sm3(body + b"dhzx")
    assert bytes(get["body_hash"]) == double_sm3(b"dhzx")
    assert post["result"] != get["result"]


def test_schema_keeps_options_beyond_previous_500_item_limit():
    options = [{"value_id": i, "value_name": f"选项{i}"} for i in range(501)]
    fields = normalize_fields([{"id": 12, "label": "材质", "required": True, "options": options}])
    assert len(fields[0]["options"]) == 501
    assert fields[0]["options"][-1] == {"label": "选项500", "value": "500"}
    with pytest.raises(TypeError):
        pure_signer.generate("appid=1", "test-agent", body="not bytes")


def test_invalid_signer_mode_does_not_make_a_platform_request(settings):
    config = settings.model_copy(update={"douyin_signer_mode": "unknown"})
    with pytest.raises(LookupError, match="invalid_configuration"):
        DouyinCategoryClient(config).category_options(make_session(), "0")


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


def test_signed_category_options_keep_tree_and_leaf_status(settings):
    def handler(request):
        if request.url.host != "fxg.jinritemai.com":
            return httpx.Response(200, json={"ok": True, "a_bogus": "signature"})
        assert request.url.path == "/product/tproduct/categoryOptionsN"
        assert request.url.params["cid"] == "0" and request.url.params["display_all"] == "0"
        return httpx.Response(200, json={"code": 0, "data": [
            {"id": 100, "name": "居家日用", "parent_cid": 0, "is_leaf": False, "enable": 1},
            {"id": 101, "name": "不可用示例", "parent_cid": 0, "is_leaf": True, "enable": 0},
        ]})
    client = DouyinCategoryClient(settings, transport=httpx.MockTransport(handler))
    assert client.category_options(make_session(), "0") == [
        {"id": "100", "name": "居家日用", "isLeaf": False, "enabled": True},
        {"id": "101", "name": "不可用示例", "isLeaf": True, "enabled": False},
    ]


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


def test_prediction_uses_full_title_image_and_keeps_all_category_levels(settings):
    title = "完整商品标题" * 20
    image = "https://images.example.test/main.jpg"
    requests = []

    def handler(request):
        if request.url.host != "fxg.jinritemai.com":
            data = json.loads(request.content)
            assert data["method"] == "POST" and data["body"]
            return httpx.Response(200, json={"ok": True, "a_bogus": "synthetic-signature"})
        assert request.url.path == "/product/tproduct/predictCategoryN"
        body = json.loads(request.content)
        requests.append(body)
        assert body["title"] == title and body["pic"] == [{"url": image}]
        assert body["scene"] == "predict_by_title_and_img" and body["publish_id"].startswith("helper_")
        return httpx.Response(200, json={"code": 0, "data": {"predict_cid": "", "candidate_category_details": [
            {"first_cid": 100, "first_cname": "居家日用", "second_cid": 101, "second_cname": "收纳工具",
             "third_cid": 102, "third_cname": "收纳架", "fourth_cid": 0, "fourth_cname": "",
             "deleted": False, "forbidden_status": 0},
            {"first_cid": 200, "first_cname": "家居", "second_cid": 201, "second_cname": "架类",
             "third_cid": 202, "third_cname": "置物架", "fourth_cid": 203, "fourth_cname": "落地架"},
        ]}})

    client = DouyinCategoryClient(settings, transport=httpx.MockTransport(handler))
    result = client.predict(make_session(), title, image)
    assert result["recommendedId"] is None  # An empty platform recommendation is not the first candidate.
    assert result["candidates"][0] == {"id": "102", "name": "收纳架", "path": "居家日用 > 收纳工具 > 收纳架",
        "levels": [{"id": "100", "name": "居家日用"}, {"id": "101", "name": "收纳工具"},
                   {"id": "102", "name": "收纳架"}], "selectable": True}
    assert result["candidates"][1]["id"] == "203" and len(result["candidates"][1]["levels"]) == 4
    assert len(requests) == 1


def test_prediction_empty_and_invalid_category_paths_are_not_invented():
    from app.modules.category_lookup.client import normalize_predictions
    assert normalize_predictions({"candidate_category_details": None, "predict_cid": ""}) == {
        "candidates": [], "recommendedId": None}
    with pytest.raises(LookupError):
        normalize_predictions({"candidate_category_details": [{"first_cid": 1, "first_cname": "居家",
            "second_cid": 0, "third_cid": 3, "third_cname": "架子"}]})
    unavailable = normalize_predictions({"predict_cid": "1", "candidate_category_details": [
        {"first_cid": 1, "first_cname": "类目", "deleted": True, "forbidden_status": 0}]})
    assert unavailable["candidates"][0]["selectable"] is False and unavailable["recommendedId"] is None


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


def test_prediction_auto_distributes_and_reports_no_recommendation(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    monkeypatch.setattr("app.modules.category_lookup.api._next", 0)
    get_settings.cache_clear()
    ids = [uuid4(), uuid4()]
    title = "商品完整标题" * 20
    class Predictor(FakeLookup):
        def predict(self, session, actual_title, image_url):
            assert session.shop_id in ids and actual_title == title and image_url == "https://example.test/main.jpg"
            return {"recommendedId": None, "candidates": []}
    class Repository:
        def export_rows(self, product_ids):
            assert len(product_ids) == 1
            if product_ids[0] == "12345678":
                return [{"source_platform": "douyin", "uu_text": "{}"}]
            package = {"product": {"title": title}, "images": {"main": [{"url": "https://example.test/main.jpg"}]}}
            if product_ids[0] == "pdd:99999999":
                package = {"goodsInfo": {"goodsName": title, "goodsImageList": ["https://example.test/main.jpg"]}}
            if product_ids[0] == "pdd:87654321":
                package = {"product": {"title": ""}, "images": {"main": [{"url": "file:///etc/passwd"}]}}
            return [{"source_platform": "pinduoduo", "uu_text": json.dumps(package)}]
    class Service:
        repository = Repository()
    app = create_application()
    from app.modules.products.api import get_service
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: Predictor(settings)
    app.dependency_overrides[get_service] = lambda: Service()
    body = {"productId": "pdd:12345678"}
    with TestClient(app) as client:
        auth = {"Authorization": "Bearer " + PRODUCT_KEY}
        a = client.post('/api/v1/category-lookup/predict', json=body, headers=auth)
        b = client.post('/api/v1/category-lookup/predict', json=body, headers=auth)
        assert a.status_code == b.status_code == 200 and a.json()['shopId'] != b.json()['shopId']
        assert a.json()['status'] == 'no_recommendation' and a.json()['candidates'] == [] and a.json()['recommendedId'] is None
        assert len(a.json()['sourceVersion']) == 64
        assert a.headers['cache-control'] == 'no-store' and COOKIE not in a.text
        legacy = client.post('/api/v1/category-lookup/predict', json={'productId': 'pdd:99999999'}, headers=auth)
        assert legacy.status_code == 200 and legacy.json()['status'] == 'no_recommendation'
        assert legacy.json()['missing'] == []
        missing = client.post('/api/v1/category-lookup/predict', json={'productId': 'pdd:87654321'}, headers=auth)
        assert missing.status_code == 200 and missing.json()['status'] == 'missing_data'
        assert missing.json()['missing'] == ['商品标题', '商品主图'] and missing.json()['shopId'] is None
        assert client.post('/api/v1/category-lookup/predict', json={'productId': '12345678'}, headers=auth).status_code == 422
        assert client.post('/api/v1/category-lookup/predict', json={'productId': 'invalid'}, headers=auth).status_code == 422
        assert client.post('/api/v1/category-lookup/predict', json=body, headers={'Authorization': 'Bearer ' + RPA_KEY}).status_code == 401
    get_settings.cache_clear()


def test_tree_and_attribute_cache_survive_restart_and_refresh_only_on_request(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    get_settings.cache_clear()
    shop_id = uuid4()
    calls = []

    class TrackedLookup(FakeLookup):
        fail = False
        revision = 1

        def category_options(self, session, parent_id):
            calls.append(("tree", parent_id))
            if self.fail:
                raise LookupError("platform_unavailable")
            return [{"id": "100" if parent_id == "0" else "101", "name": f"类目{self.revision}",
                     "isLeaf": parent_id != "0", "enabled": True}]

        def schema(self, session, category_id, title):
            calls.append(("schema", category_id))
            if self.fail:
                raise LookupError("platform_unavailable")
            return [{"id": "12", "label": f"材质{self.revision}", "required": True, "options": []}]

    lookup = TrackedLookup(settings)
    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral([shop_id])
    app.dependency_overrides[get_lookup] = lambda: lookup
    auth = {"Authorization": "Bearer " + PRODUCT_KEY}
    with TestClient(app) as client:
        path = '/api/v1/category-lookup/tree'
        root = client.post(path, json={}, headers=auth)
        assert root.status_code == 200 and root.json()['items'][0]['isLeaf'] is False
        child_body = {"parentId": "100", "shopId": str(shop_id)}
        child = client.post(path, json=child_body, headers=auth)
        assert child.json()['items'][0]['isLeaf'] is True
        assert client.post(path, json={}, headers=auth).json()['fromCache'] is True
        assert client.post(path, json=child_body, headers=auth).json()['fromCache'] is True
        schema = '/api/v1/category-lookup/schema/auto'
        body = {"categoryId": "101", "title": "旧标题"}
        assert client.post(schema, json=body, headers=auth).json()['attributes'][0]['label'] == '材质1'
        assert client.post(schema, json={**body, "title": "另一个商品"}, headers=auth).json()['attributes'][0]['label'] == '材质1'
        assert calls == [("tree", "0"), ("tree", "100"), ("schema", "101")]

        lookup.fail = True
        assert client.post(path, json={"refresh": True}, headers=auth).status_code == 502
        assert client.post(path, json=child_body, headers=auth).json()['fromCache'] is True
        assert client.post(schema, json={**body, "refresh": True}, headers=auth).status_code == 502
        assert client.post(schema, json=body, headers=auth).json()['attributes'][0]['label'] == '材质1'

        lookup.fail = False
        lookup.revision = 2
        assert client.post(path, json={"refresh": True}, headers=auth).json()['items'][0]['name'] == '类目2'
        assert client.post(path, json=child_body, headers=auth).json()['fromCache'] is False
        assert client.post(schema, json={**body, "refresh": True}, headers=auth).json()['attributes'][0]['label'] == '材质2'
        assert client.post(schema, json=body, headers=auth).json()['attributes'][0]['label'] == '材质2'
        assert client.post(path, json={}, headers={"Authorization": "Bearer " + RPA_KEY}).status_code == 401
    from app.modules.category_lookup.cache import CategoryCache
    cache = CategoryCache(settings.category_cache_file)
    assert cache.get("tree", str(shop_id), "100")[0]["name"] == "类目2"
    assert cache.get("schema", str(shop_id), "101")[0]["label"] == "材质2"
    assert COOKIE.encode() not in settings.category_cache_file.read_bytes()
    assert "旧标题".encode() not in settings.category_cache_file.read_bytes()
    get_settings.cache_clear()


def test_schema_cache_isolated_by_shop_and_missing_cache_fails_closed(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_KEY)
    get_settings.cache_clear()
    ids = [uuid4(), uuid4()]
    calls = []

    class ShopSpecificLookup(FakeLookup):
        def schema(self, session, category_id, title):
            calls.append(session.shop_id)
            return [{"id": "12", "label": str(session.shop_id), "required": True, "options": []}]

    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: ShopSpecificLookup(settings)
    auth = {"Authorization": "Bearer " + PRODUCT_KEY}
    with TestClient(app) as client:
        path = '/api/v1/category-lookup/schema'
        for shop_id in ids:
            body = {"shopId": str(shop_id), "categoryId": "1000010075"}
            assert client.post(path, json=body, headers=auth).json()['attributes'][0]['label'] == str(shop_id)
            assert client.post(path, json=body, headers=auth).json()['attributes'][0]['label'] == str(shop_id)
        assert calls == ids
        assert client.post('/api/v1/category-lookup/tree', json={"shopId": str(uuid4())}, headers=auth).status_code == 403
        bad_settings = settings.model_copy(update={"category_cache_file": tmp_path / "missing" / "cache.sqlite3"})
        app.dependency_overrides[get_lookup] = lambda: ShopSpecificLookup(bad_settings)
        response = client.post('/api/v1/category-lookup/tree', json={}, headers=auth)
        assert response.status_code == 503 and "缓存不可用" in response.json()['detail']
        assert len(calls) == 2
    get_settings.cache_clear()


def test_old_inflight_tree_result_cannot_repopulate_after_manual_refresh(settings):
    from app.modules.category_lookup.cache import CategoryCache
    cache = CategoryCache(settings.category_cache_file)
    version = cache.tree_version()
    cache.put("tree", "shop", "0", [{"name": "new"}], refresh_tree=True)
    cache.put("tree", "shop", "123", [{"name": "old"}], tree_version=version)
    assert cache.get("tree", "shop", "0") == [{"name": "new"}]
    assert cache.get("tree", "shop", "123") is None
    schema_version = cache.schema_version("123")
    cache.put("schema", "shop", "123", [{"label": "new"}], refresh_schema=True)
    cache.put("schema", "other-shop", "123", [{"label": "old"}], schema_version=schema_version)
    assert cache.get("schema", "shop", "123") == [{"label": "new"}]
    assert cache.get("schema", "other-shop", "123") is None


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
