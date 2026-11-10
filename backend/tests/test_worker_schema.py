import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.modules.category_lookup.api import Attribute
from app.modules.category_lookup.client import normalize_fields
from app.modules.prechecks.service import check_product
from app.modules.prechecks.worker_schema import (
    MAX_WORKER_SCHEMA_BYTES, WorkerSchemaResultError, read_worker_schema,
)


def envelope(items, *, category_id="1000001535"):
    return {
        "kind": "douyin.category_schema", "category_id": category_id,
        "device_id": "device-1", "local_shop_id": "local-shop-1", "platform_shop_id": "platform-shop-1",
        "http_status": 200, "platform_code": 0, "items": items,
    }


@pytest.mark.parametrize("category_id", ["1000001535", "1000005146"])
def test_existing_real_field_samples_keep_identical_rules_after_transport(category_id):
    path = Path(__file__).parent / "fixtures" / f"douyin-schema-{category_id}.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    transported = json.loads(json.dumps(envelope(items, category_id=category_id), ensure_ascii=False))
    result = read_worker_schema(transported, expected_category_id=category_id)
    expected = [Attribute.model_validate(field).model_dump() for field in normalize_fields(items)]
    assert [field.model_dump() for field in result.attributes] == expected


def test_large_options_and_unknown_measure_rules_are_preserved():
    items = [
        {"id": "hidden", "hidden": True},
        {"id": "off", "available": False},
        {"id": "large", "label": "多选", "required": True,
         "additions": {"ui_type": "multi_select", "diy_type": 0},
         "rules": [{"type": "max_input_num", "value": 5}],
         "options": [{"value_id": str(i), "value_name": f"候选项{i:05d}"} for i in range(5000)]},
        {"id": "measure", "label": "尺寸", "additions": {"ui_type": "measure",
         "measure_templates": [{"template_id": "t", "display_name": "尺寸", "value_modules": [{
             "module_id": "m", "input_type": "input", "unit_linkage": {"x": 1},
             "unit_options": [{"label": "cm", "value": "cm"}],
             "validate_rule": {"data_type": "int", "unit_rules": []},
         }]}]}},
    ]
    payload = json.loads(json.dumps(envelope(items), ensure_ascii=False))
    assert len(json.dumps(payload, ensure_ascii=False).encode()) > 64 * 1024
    result = read_worker_schema(payload, expected_category_id="1000001535")
    expected = [Attribute.model_validate(field).model_dump() for field in normalize_fields(items)]
    assert [field.model_dump() for field in result.attributes] == expected
    assert [field.id for field in result.attributes] == ["large", "measure"]
    assert result.attributes[0].maxValues == 5
    assert len(result.attributes[0].options) == 5000
    assert result.attributes[0].options[-1].value == "4999"
    assert result.attributes[1].ruleStatus == "unknown"


@pytest.mark.parametrize("code", [0, "0"])
def test_success_code_accepts_integer_or_string_zero(code):
    payload = envelope([])
    payload["platform_code"] = code
    assert read_worker_schema(payload, expected_category_id="1000001535").attributes == []


@pytest.mark.parametrize(("changed", "reason"), [
    ({"category_id": "999"}, "category_mismatch"),
    ({"http_status": 500}, "platform_request_failed"),
    ({"platform_code": 10008}, "platform_request_failed"),
    ({"platform_code": False}, "platform_request_failed"),
    ({"platform_code": True}, "platform_request_failed"),
    ({"platform_code": "00"}, "platform_request_failed"),
    ({"platform_code": ""}, "platform_request_failed"),
    ({"items": None}, "invalid_result"),
    ({"local_shop_id": ""}, "invalid_result"),
    ({"cookie": "must-not-be-accepted"}, "invalid_result"),
])
def test_rejects_wrong_category_failure_and_unexpected_fields(changed, reason):
    payload = envelope([])
    payload.update(changed)
    with pytest.raises(WorkerSchemaResultError, match=reason):
        read_worker_schema(payload, expected_category_id="1000001535")


def test_oversize_is_rejected_without_truncation():
    payload = envelope([{"id": "one", "name": "x" * MAX_WORKER_SCHEMA_BYTES}])
    with pytest.raises(WorkerSchemaResultError, match="result_too_large"):
        read_worker_schema(payload, expected_category_id="1000001535")


def test_precheck_reuses_worker_schema_and_keeps_local_product_rules():
    detail = {"product": {"source_platform": "douyin", "title": "商品", "main_image_url": "https://example.invalid/a"},
              "images": [], "skus": [{"current_price": "9.90"}], "sourceCategoryId": "1000001535",
              "sourceAttributes": [], "targetCategory": [], "targetAttributes": []}
    service = SimpleNamespace(repository=SimpleNamespace(detail=lambda _: deepcopy(detail)))
    items = [{"id": "brand", "label": "品牌", "required": True, "type": "text"}]
    schema = read_worker_schema(envelope(items), expected_category_id="1000001535")
    with patch("app.modules.prechecks.service.schema_auto", side_effect=AssertionError("unexpected platform request")):
        result = check_product("12345678", service, None, None, schema_override=schema)
    assert result["status"] == "needs_completion"
    assert result["issues"] == ["品牌未填写"]
    detail["sourceCategoryId"] = "999"
    with pytest.raises(ValueError, match="预检类目已变化"):
        check_product("12345678", service, None, None, schema_override=schema)
