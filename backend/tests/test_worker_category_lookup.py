from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_application
from app.modules.category_lookup.api import get_central, get_lookup
from app.modules.category_lookup.client import DouyinCategoryClient
from app.modules.category_lookup import worker_lookup
from app.modules.category_lookup.cache import CategoryCache
from app.modules.central.client import CentralShop


def test_interactive_category_result_is_returned_directly_without_central_session(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, category_cache_file=tmp_path / "categories.sqlite3", worker_precheck_enabled=True)
    task_id, device_id, shop_id = uuid4(), uuid4(), uuid4()
    seen = []

    class Central:
        def __init__(self, settings):
            pass

        def submit_worker_precheck(self, claim, category_id, title, **options):
            seen.append((claim, category_id, title, options))
            context = SimpleNamespace(task_id=task_id, device_id=device_id, category_id="0", operation="tree",
                                      local_shop_id="local", platform_shop_id="shop")
            result = {"kind": "douyin.category_schema", "category_id": "0", "device_id": str(device_id),
                      "local_shop_id": "local", "platform_shop_id": "shop", "operation": "tree",
                      "http_status": 200, "platform_code": 0,
                      "data": [{"id": 1, "name": "家居", "parent_cid": 0, "is_leaf": False}]}
            worker_lookup.receive_lookup_result(settings, context,
                SimpleNamespace(status="success", result=result), "a" * 64)
            return SimpleNamespace(task_id=task_id)

    monkeypatch.setattr(worker_lookup, "CentralApplicationClient", Central)
    data = worker_lookup.lookup(settings, operation="tree", category_id="0", title="商品", shop_id=shop_id)
    assert data == [{"id": "1", "name": "家居", "isLeaf": False, "enabled": True}]
    assert seen[0][3]["delivery"] == "product" and seen[0][3]["shop_id"] == shop_id
    assert seen[0][3]["full_category_tree"] is True
    assert CategoryCache(settings.category_cache_file).take_worker_result(str(task_id)) is None


def test_wrong_worker_or_unknown_result_field_is_rejected(tmp_path):
    settings = Settings(_env_file=None, category_cache_file=tmp_path / "categories.sqlite3")
    context = SimpleNamespace(task_id=uuid4(), device_id=uuid4(), category_id="0", operation="tree",
                              local_shop_id="local", platform_shop_id="shop")
    result = {"kind": "douyin.category_schema", "category_id": "0", "device_id": str(uuid4()),
              "local_shop_id": "local", "platform_shop_id": "shop", "operation": "tree",
              "http_status": 200, "platform_code": 0, "data": []}
    with pytest.raises(ValueError):
        worker_lookup.receive_lookup_result(settings, context,
            SimpleNamespace(status="success", result=result), "a" * 64)


@pytest.mark.parametrize(("operation", "data"), [
    ("tree", [{"id": 1, "name": "", "is_leaf": False}]),
    ("predict", {"candidate_category_details": [{"first_cid": "1"}]}),
])
def test_invalid_platform_category_result_ends_lookup_without_redelivery(tmp_path, operation, data):
    settings = Settings(_env_file=None, category_cache_file=tmp_path / "categories.sqlite3")
    context = SimpleNamespace(task_id=uuid4(), device_id=uuid4(), category_id="0", operation=operation,
                              local_shop_id="local", platform_shop_id="shop")
    result = {"kind": "douyin.category_schema", "category_id": "0", "device_id": str(context.device_id),
              "local_shop_id": "local", "platform_shop_id": "shop", "operation": operation,
              "http_status": 200, "platform_code": 0, "data": data}
    worker_lookup.receive_lookup_result(settings, context, SimpleNamespace(status="success", result=result), "a" * 64)
    stored = CategoryCache(settings.category_cache_file).take_worker_result(str(context.task_id))
    assert stored == {"digest": "a" * 64, "status": "failed", "stage": "result",
                      "error": "PLATFORM_CATEGORY_INVALID", "code": 0}


def test_product_category_routes_all_use_direct_worker_results(tmp_path, monkeypatch):
    token = "synthetic-product-token-0123456789"
    monkeypatch.setenv("BACKEND_API_TOKEN", token)
    get_settings.cache_clear()
    settings = Settings(_env_file=None, category_cache_file=tmp_path / "categories.sqlite3",
                        worker_precheck_enabled=True, douyin_category_lookup_enabled=True)
    shop_id, device_id = uuid4(), uuid4()
    operations = []

    class Central:
        def __init__(self, settings=None):
            pass

        def list_shops(self):
            return [CentralShop(shop_id=shop_id, display_name="已映射店铺", platform="douyin", session_status="captured")]

        def submit_worker_precheck(self, claim, category_id, title, **options):
            operation = options["operation"]
            assert options["delivery"] == "product" and options["shop_id"] == shop_id
            assert options.get("full_category_tree", False) is (operation == "tree")
            operations.append(operation)
            task_id = uuid4()
            context = SimpleNamespace(task_id=task_id, device_id=device_id, category_id=category_id,
                                      operation=operation, local_shop_id="local", platform_shop_id="shop")
            identity = {"kind": "douyin.category_schema", "category_id": category_id, "device_id": str(device_id),
                        "local_shop_id": "local", "platform_shop_id": "shop", "http_status": 200, "platform_code": 0}
            if operation == "schema":
                result = {**identity, "items": [{"id": "1", "label": "材质", "required": True}]}
            else:
                data = {"tree": [{"id": 1, "name": "家居", "parent_cid": 0, "is_leaf": False}],
                        "search": [{"id": "1", "name": "家居", "path": "家居"}],
                        "predict": {"predict_cid": "1", "candidate_category_details": [
                            {"first_cid": "1", "first_cname": "家居", "deleted": False, "forbidden_status": 0}]}}[operation]
                result = {**identity, "operation": operation, "data": data}
            worker_lookup.receive_lookup_result(settings, context, SimpleNamespace(status="success", result=result), "a" * 64)
            return SimpleNamespace(task_id=task_id)

    monkeypatch.setattr(worker_lookup, "CentralApplicationClient", Central)
    app = create_application()
    app.dependency_overrides[get_central] = lambda: Central()
    app.dependency_overrides[get_lookup] = lambda: DouyinCategoryClient(settings)
    auth = {"Authorization": "Bearer " + token}
    with TestClient(app) as client:
        assert client.post("/api/v1/category-lookup/tree", json={}, headers=auth).json()["items"][0]["name"] == "家居"
        assert client.post("/api/v1/category-lookup/search", json={"keyword": "家居"}, headers=auth).json()["candidates"][0]["id"] == "1"
        prediction = client.post("/api/v1/category-lookup/predict/manual", json={"title": "商品",
                                  "imageUrl": "https://image.test/a.jpg"}, headers=auth).json()
        assert prediction["recommendedId"] == "1"
        schema = client.post("/api/v1/category-lookup/schema/auto", json={"categoryId": "1"}, headers=auth).json()
        assert schema["attributes"][0]["label"] == "材质"
    assert operations == ["tree", "search", "predict", "schema"]
    get_settings.cache_clear()
