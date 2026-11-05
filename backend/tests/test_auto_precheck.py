from types import SimpleNamespace as Node
from unittest.mock import Mock, patch

from app.modules.category_lookup.api import Attribute, Option
from app.modules.category_lookup.attribute_values import UNVERIFIED
from app.modules.prechecks.service import _attribute_problems, _missing_required, check_product


def test_required_values_match_original_id_or_unambiguous_pdd_name():
    fields = [Attribute(id="1", label="材质", required=True, options=[Option(label="塑料", value="5")],
                        control="single", allowCustom=False, ruleStatus="confirmed"),
              Attribute(id="2", label="品牌", required=True, options=[], control="text", ruleStatus="confirmed")]
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
    fields = [Attribute(id="1", label="材质", required=True, options=[], control="text", ruleStatus="confirmed"),
              Attribute(id="2", label="品牌", required=True, options=[], control="text", ruleStatus="confirmed")]
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
                  control="multi", allowCustom=True, ruleStatus="confirmed"),
        Attribute(id="2", label="材质", required=True, options=[Option(label="塑料", value="2")],
                  control="single", allowCustom=False, ruleStatus="confirmed"),
        Attribute(id="3", label="容量", required=True, options=[], control="number", allowCustom=False,
                  ruleStatus="confirmed"),
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


def test_option_id_is_authoritative_and_unknown_rules_remain_pending():
    restricted = Attribute(id="1", label="材质", required=True,
        options=[Option(label="新显示名", value="platform-1")], control="single",
        allowCustom=False, ruleStatus="confirmed")
    unknown = Attribute(id="2", label="尺寸", required=False, options=[], control="unknown",
        allowCustom=None, ruleStatus="unknown")
    source = [
        {"id": "1", "name": "材质", "values": ["旧显示名"],
         "valueItems": [{"valueId": "platform-1", "name": "旧显示名"}]},
        {"id": "2", "name": "尺寸", "values": ["10×20 cm"]},
    ]
    assert [(field.label, problem) for field, problem in
            _attribute_problems([restricted, unknown], source, [], "douyin")] == [("尺寸", UNVERIFIED)]


def test_unknown_rule_cannot_report_success_or_invent_platform_message():
    detail = {"product": {"source_platform": "douyin", "title": "商品", "main_image_url": "https://example.invalid/a"},
              "images": [], "skus": [{"current_price": "9.90"}], "sourceCategoryId": "100",
              "sourceAttributes": [{"id": "1", "name": "未知属性", "values": ["旧值"]}],
              "targetCategory": [], "targetAttributes": []}
    field = Attribute(id="1", label="未知属性", required=False, options=[])
    service = Node(repository=Node(detail=lambda _: detail))
    with patch("app.modules.prechecks.service.schema_auto", return_value=Node(attributes=[field])):
        result = check_product("12345678", service, None, None)
    assert result["status"] == "failed" and result["issues"] == [] and result["issueDetails"] == []


def test_old_queued_rule_hint_is_removed_without_falsely_passing():
    from app.modules.prechecks.queue import present_result
    original = {"status": "needs_completion", "issues": ["尺寸规则待核对", "品牌未填写"], "issueDetails": [
        {"fieldId": "4738", "message": "尺寸规则待核对"}, {"fieldId": "1687", "message": "品牌未填写"}]}
    result = present_result(original)
    assert result == {"status": "failed", "issues": ["品牌未填写"],
                      "issueDetails": [{"fieldId": "1687", "message": "品牌未填写"}]}
    assert original["issues"] == ["尺寸规则待核对", "品牌未填写"]
    assert present_result({"status": "needs_completion", "issues": ["品牌未填写"]}) == {
        "status": "needs_completion", "issues": ["品牌未填写"]}


def test_new_douyin_precheck_writes_real_no_brand_then_leaves_stale_claim_unfinished():
    from app.modules.prechecks.runner import PrecheckRunner

    product_id = "1234567890123456789"
    detail = {"product": {"source_platform": "douyin", "title": "新采集商品", "title_status": "采集完成"},
              "sourceCategoryId": "1000008074"}
    repository = Node(detail=Mock(return_value=detail), set_default_brand=Mock(return_value="updated"))
    runner = object.__new__(PrecheckRunner)
    runner.service = Node(repository=repository)
    runner.central, runner.lookup, runner.queue = object(), object(), Mock()
    brand = Attribute(id="1687", label="品牌", required=True,
        options=[Option(label="无品牌", value="596120136")], control="single",
        allowCustom=False, ruleStatus="confirmed")
    claim = {"product_id": product_id, "revision": 1, "attempts": 1}
    with patch("app.modules.prechecks.runner.schema_auto", return_value=Node(attributes=[brand])), \
            patch("app.modules.prechecks.runner.check_product") as check:
        runner.process(claim)
    repository.set_default_brand.assert_called_once_with(product_id, {
        "fieldId": "1687", "fieldName": "品牌", "valueId": "596120136", "valueName": "无品牌",
    }, force=False, mark_modified=False)
    check.assert_not_called()
    runner.queue.complete.assert_not_called()


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
