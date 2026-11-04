from types import SimpleNamespace as Node
from unittest.mock import patch

from app.modules.category_lookup.api import Attribute, Option
from app.modules.prechecks.service import _attribute_problems, _missing_required, check_product


def test_required_values_match_original_id_or_unambiguous_pdd_name():
    fields = [Attribute(id="1", label="材质", required=True, options=[Option(label="塑料", value="5")]),
              Attribute(id="2", label="品牌", required=True, options=[])]
    source = [{"id": "1", "name": "材质", "values": ["塑料"]}]
    assert _missing_required(fields, source, [], "douyin") == ["品牌"]
    invalid = _attribute_problems(fields, [{"id": "99", "name": "材质", "values": ["木材"]}], [], "pinduoduo")
    assert [(field.label, problem) for field, problem in invalid] == [("材质", "包含无效选项"), ("品牌", "未填写")]
    assert _missing_required(fields, source, [{"id": "1", "name": "材质", "values": []}], "pinduoduo") == ["材质", "品牌"]


def test_douyin_auto_check_uses_original_category_and_lists_missing_names():
    product_id = "12345678"
    detail = {"product": {"source_platform": "douyin", "title": "商品", "main_image_url": "https://example.invalid/a"},
              "images": [], "skus": [{"current_price": "9.90"}], "sourceCategoryId": "100",
              "sourceAttributes": [{"id": "1", "name": "材质", "values": ["棉"]}],
              "targetCategory": [], "targetAttributes": []}
    fields = [Attribute(id="1", label="材质", required=True, options=[]),
              Attribute(id="2", label="品牌", required=True, options=[])]
    service = Node(repository=Node(detail=lambda _: detail))
    with patch("app.modules.prechecks.service.schema_auto", return_value=Node(attributes=fields)) as schema, \
            patch("app.modules.prechecks.service.predict") as predict:
        result = check_product(product_id, service, None, None)
    assert result["status"] == "needs_completion" and result["issues"] == ["品牌未填写"]
    assert result["issueDetails"] == [{"code": "attribute_missing", "message": "品牌未填写",
                                       "tab": "attributes", "fieldId": "2"}]
    assert schema.call_args.args[0].categoryId == "100"
    predict.assert_not_called()


def test_real_schema_rules_validate_multi_custom_number_and_sku_location():
    fields = [
        Attribute(id="1", label="适用场景", required=True, options=[Option(label="家用", value="1")],
                  control="multi", allowCustom=True),
        Attribute(id="2", label="材质", required=True, options=[Option(label="塑料", value="2")],
                  control="single", allowCustom=False),
        Attribute(id="3", label="容量", required=True, options=[], control="number", allowCustom=False),
    ]
    detail = {"product": {"source_platform": "douyin", "title": "商品", "main_image_url": "https://example.invalid/a"},
              "images": [], "skus": [{"sku_id": "ok", "current_price": "9.90"},
                                      {"sku_id": "bad", "current_price": "0"}],
              "sourceCategoryId": "100", "sourceAttributes": [
                  {"id": "1", "name": "适用场景", "values": ["露营"]},
                  {"id": "2", "name": "材质", "values": ["木材"]},
                  {"id": "3", "name": "容量", "values": ["很多"]},
              ], "targetCategory": [], "targetAttributes": []}
    service = Node(repository=Node(detail=lambda _: detail))
    with patch("app.modules.prechecks.service.schema_auto", return_value=Node(attributes=fields)):
        result = check_product("12345678", service, None, None)
    assert result["issues"] == ["第 2 个 SKU 价格无效", "材质包含无效选项", "容量数字无效"]
    assert result["issueDetails"][0] == {"code": "sku_price_invalid", "message": "第 2 个 SKU 价格无效",
                                         "tab": "sku", "fieldId": "price", "skuIndex": 1, "skuId": "bad"}


def test_auto_precheck_result_api_requires_authentication_and_enabled_feature(tmp_path):
    from fastapi.testclient import TestClient
    from app.core.config import Settings, get_settings
    from app.main import create_application

    settings = Settings(data_root=tmp_path, api_token="synthetic-admin-token", auto_precheck_enabled=False)
    app = create_application()
    app.dependency_overrides[get_settings] = lambda: settings
    with patch("app.core.security.access.get_settings", return_value=settings), \
            patch("app.modules.prechecks.api.get_settings", return_value=settings), TestClient(app) as client:
        assert client.post("/api/v1/prechecks/query", json={"productIds": ["12345678"]}).status_code == 401
        response = client.post("/api/v1/prechecks/query", json={"productIds": ["12345678"]},
                               headers={"Authorization": "Bearer synthetic-admin-token"})
        assert response.status_code == 503


def test_manual_and_batch_precheck_use_the_same_durable_queue_endpoint(tmp_path):
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from app.core.config import Settings, get_settings
    from app.main import create_application

    settings = Settings(data_root=tmp_path, api_token="synthetic-admin-token", auto_precheck_enabled=True)
    queued = [{"productId": "12345678", "revision": 7, "state": "pending", "result": None,
               "error": None, "updatedAt": datetime.now(timezone.utc)}]
    app = create_application()
    app.dependency_overrides[get_settings] = lambda: settings
    with patch("app.core.security.access.get_settings", return_value=settings), \
            patch("app.modules.prechecks.api.get_settings", return_value=settings), \
            patch("app.modules.prechecks.api.get_database_engine", return_value=object()), \
            patch("app.modules.prechecks.api.PrecheckQueue") as queue, TestClient(app) as client:
        queue.return_value.enqueue.return_value = queued
        response = client.post("/api/v1/prechecks/run", json={"productIds": ["12345678", "87654321"]},
                               headers={"Authorization": "Bearer synthetic-admin-token"})
    assert response.status_code == 200
    assert response.json()["items"][0]["revision"] == 7
    assert response.json()["missing"] == ["87654321"]
    queue.return_value.enqueue.assert_called_once_with(["12345678", "87654321"])
