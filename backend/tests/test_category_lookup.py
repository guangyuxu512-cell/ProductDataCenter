"""Contract tests for the two read-only platform calls and authorization."""
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_application
from app.modules.category_lookup.api import get_central, get_lookup
from app.modules.category_lookup.client import LookupError, normalize_fields
from app.modules.central.client import CentralShop

PRODUCT_KEY = "synthetic-product-token-1234567890"
RPA_KEY = "synthetic-rpa-token-1234567890"
COOKIE = "synthetic-session-value-never-expose"


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, douyin_category_lookup_enabled=True,
                    category_cache_file=tmp_path / "categories.sqlite3",
                    worker_precheck_enabled=True, api_token=PRODUCT_KEY, rpa_api_token=RPA_KEY)








def test_schema_keeps_options_beyond_previous_500_item_limit():
    options = [{"value_id": i, "value_name": f"选项{i}"} for i in range(501)]
    fields = normalize_fields([{"id": 12, "label": "材质", "required": True, "options": options}])
    assert len(fields[0]["options"]) == 501
    assert fields[0]["options"][-1] == {"label": "选项500", "value": "500"}


def test_integer_required_flag_remains_supported():
    assert normalize_fields([{"id": 12, "label": "材质", "required": 1}])[0]["required"] is True


def test_schema_uses_platform_control_metadata_instead_of_guessing_labels():
    fields = normalize_fields([
        {"id": 1, "label": "适用场景", "additions": {"ui_type": "multi_select", "diy_type": 1},
         "options": [{"value_id": 10, "value_name": "家用"}]},
        {"id": 2, "label": "型号", "additions": {"ui_type": "select", "diy_type": 0},
         "options": [{"value_id": 20, "value_name": "标准"}]},
        {"id": 3, "label": "容量", "additions": {"ui_type": "number", "diy_type": 0}, "options": []},
        {"id": 4, "label": "备注", "additions": {"ui_type": "text", "diy_type": 0}, "options": []},
        {"id": 5, "label": "尺寸", "additions": {"ui_type": "measure", "diy_type": 0}, "options": []},
    ])
    assert [(field["control"], field["allowCustom"], field["ruleStatus"]) for field in fields] == [
        ("multi", True, "confirmed"), ("single", False, "confirmed"),
        ("number", False, "confirmed"), ("text", False, "confirmed"),
        ("unknown", None, "unknown"),
    ]


def test_real_response_shape_exposes_custom_multi_and_no_brand_option():
    fields = normalize_fields([
        {"id": 810, "label": "功能", "required": False,
         "additions": {"ui_type": "multi_select", "diy_type": 1, "property_type": 0},
         "options": [{"value_id": 619191, "value_name": "保湿"}]},
        {"id": 2595, "label": "适用年龄", "required": False,
         "additions": {"ui_type": "multi_select", "diy_type": 0, "property_type": 0},
         "options": [{"value_id": 1, "value_name": "成人"}]},
        {"id": 1687, "label": "品牌", "required": True,
         "additions": {"ui_type": "search", "diy_type": 0, "property_type": 0},
         "options": [{"value_id": "596120136", "value_name": "无品牌"}]},
    ])
    assert fields[0]["control"] == "multi" and fields[0]["allowCustom"] is True
    assert fields[1]["control"] == "multi" and fields[1]["allowCustom"] is False
    assert fields[2]["options"] == [{"label": "无品牌", "value": "596120136"}]




















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
            assert session in ids and actual_title == title and image_url == "https://example.test/main.jpg"
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


def test_manual_draft_prediction_uses_current_title_and_image_without_creating_product(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    get_settings.cache_clear()
    shop_id = uuid4()
    seen = []
    class Predictor(FakeLookup):
        def predict(self, session, title, image_url):
            seen.append((session, title, image_url))
            return {"recommendedId": "11", "candidates": [{"id": "11", "name": "汤勺", "path": "餐具 > 汤勺",
                    "levels": [{"id": "10", "name": "餐具"}, {"id": "11", "name": "汤勺"}], "selectable": True}]}
    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral([shop_id])
    app.dependency_overrides[get_lookup] = lambda: Predictor(settings)
    title = "完整手动商品标题" * 20
    image = "https://images.example.test/rpa/v1/product-images/test.jpg"
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + PRODUCT_KEY}
        missing = client.post('/api/v1/category-lookup/predict/manual', json={'title': ' ', 'imageUrl': ''}, headers=headers)
        assert missing.status_code == 200 and missing.json()['missing'] == ['商品标题', '商品主图']
        assert not seen
        result = client.post('/api/v1/category-lookup/predict/manual', json={'title': title, 'imageUrl': image}, headers=headers)
        assert result.status_code == 200 and result.json()['status'] == 'recommended'
        assert result.json()['candidates'][0]['levels'][-1]['name'] == '汤勺'
        assert seen == [(shop_id, title, image)]
        assert result.headers['cache-control'] == 'no-store'
        assert client.post('/api/v1/category-lookup/predict/manual', json={'title': title, 'imageUrl': image}).status_code == 401
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
            calls.append(session)
            return [{"id": "12", "label": str(session), "required": True, "options": []}]

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


def test_tree_reports_available_shops_and_keeps_each_shop_tree_separate(settings, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_KEY)
    get_settings.cache_clear()
    first, second = sorted((uuid4(), uuid4()), key=str)
    class Shops(FakeCentral):
        def list_shops(self):
            return [CentralShop(shop_id=first, display_name="甲店", platform="douyin", session_status="valid"),
                    CentralShop(shop_id=second, display_name="乙店", platform="douyin", session_status="valid")]
    class Lookup(FakeLookup):
        def category_options(self, shop, parent):
            return ([{"id": "1000011128", "name": "热水袋", "isLeaf": True, "enabled": True}]
                    if shop == second else [])
    app = create_application()
    app.dependency_overrides[get_central] = lambda: Shops([first, second])
    app.dependency_overrides[get_lookup] = lambda: Lookup(settings)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + PRODUCT_KEY}
        path = '/api/v1/category-lookup/tree'
        first_response = client.post(path, json={"shopId": str(first)}, headers=headers).json()
        second_response = client.post(path, json={"shopId": str(second)}, headers=headers).json()
        assert first_response['items'] == []
        assert second_response['items'][0]['name'] == '热水袋'
        assert first_response['shops'] == [{"id": str(first), "name": "甲店"}, {"id": str(second), "name": "乙店"}]
        assert client.post(path, json={"shopId": str(second)}, headers=headers).json()['fromCache'] is True
        assert client.post(path, json={"shopId": str(uuid4())}, headers=headers).status_code == 403
    get_settings.cache_clear()


def test_live_schema_change_compares_same_shop_and_fences_inflight(settings):
    from app.modules.category_lookup.cache import CategoryCache
    cache = CategoryCache(settings.category_cache_file)
    fields = [{"id": "1", "label": "品牌", "required": True,
               "options": [{"label": "乙", "value": "2"}, {"label": "甲", "value": "1"}]}]
    cache.put("schema", "first", "123", fields)
    cache.put("schema", "second", "123", fields)
    cache.put("schema", "second", "124", fields)
    version = cache.schema_version("123")
    reordered = [{**fields[0], "options": list(reversed(fields[0]['options']))}]
    assert not cache.invalidate_changed_schema("first", "123", reordered)
    assert cache.get("schema", "first", "123") == fields
    assert cache.invalidate_changed_schema("first", "123", [{**reordered[0], "required": False}])
    assert cache.get("schema", "first", "123") is None
    assert cache.get("schema", "second", "123") is None
    assert cache.get("schema", "second", "124") == fields
    cache.put("schema", "first", "123", fields, schema_version=version)
    assert cache.get("schema", "first", "123") is None
    assert not cache.invalidate_changed_schema("missing", "123", fields)


def test_legacy_schema_cache_is_one_time_miss_and_v3_keeps_controls(settings):
    import json
    from app.modules.category_lookup.cache import CategoryCache
    cache = CategoryCache(settings.category_cache_file)
    with cache._transaction() as db:
        db.execute("INSERT INTO category_cache(kind,shop_id,cache_key,payload) VALUES ('schema','shop','legacy',?)",
                   (json.dumps([{"id": "1", "control": "single"}]),))
    assert cache.get("schema", "shop", "legacy") is None
    with cache._transaction() as db:
        db.execute("UPDATE category_cache SET payload=? WHERE kind='schema' AND shop_id='shop' AND cache_key='legacy'",
                   (json.dumps({"formatVersion": 2, "attributes": [{"id": "1", "control": "unknown"}]}),))
    assert cache.get("schema", "shop", "legacy") is None
    value = [{"id": "1", "control": "multi", "allowCustom": True, "ruleStatus": "confirmed"}]
    cache.put("schema", "shop", "legacy", value)
    assert cache.get("schema", "shop", "legacy") == value


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
            attempted.append((session, category_id, sent_title))
            if session == ids[0]:
                raise LookupError("session_expired", 10008)
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
            attempted.append(session)
            if session == ids[0]:
                raise LookupError("session_expired", 10008)
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
        reason = "session_expired"
        code = 10008

        def search(self, session, keyword):
            attempted.append(session)
            raise LookupError(self.reason, self.code)

    failure = FailingLookup(settings)
    app = create_application()
    app.dependency_overrides[get_central] = lambda: FakeCentral(ids)
    app.dependency_overrides[get_lookup] = lambda: failure
    with TestClient(app) as client:
        auth = {"Authorization": "Bearer " + PRODUCT_KEY}
        response = client.post('/api/v1/category-lookup/search', json={"keyword": "勺子"}, headers=auth)
        assert response.status_code == 502
        assert "已授权设备没有可用的店铺登录状态" in response.json()['detail']
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
                assigned[session] += 1
                active[session] += 1
                peak[session] = max(peak[session], active[session])
            sleep(0.02)
            with lock:
                active[session] -= 1
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
