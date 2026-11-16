from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.category_lookup import worker_lookup
from app.modules.category_lookup.cache import CategoryCache


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
