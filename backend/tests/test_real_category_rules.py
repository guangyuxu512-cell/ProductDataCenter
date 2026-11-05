"""Regression cases use sanitized getSchema fields captured from the two requested classes."""
import json
from pathlib import Path

from app.modules.category_lookup.api import Attribute
from app.modules.category_lookup.attribute_values import measure_valid, normalize_multi_values
from app.modules.category_lookup.client import normalize_fields
from app.modules.prechecks.service import _attribute_problem


def real_fields(category):
    raw = json.loads((Path(__file__).parent / "fixtures" / f"douyin-schema-{category}.json").read_text(encoding="utf-8"))
    return {item["id"]: Attribute.model_validate(item) for item in normalize_fields(raw)}


def test_real_measure_templates_and_plain_text_are_distinct():
    storage = real_fields("1000005146")
    toy = real_fields("1000001535")
    assert storage["989"].control == toy["989"].control == "text"
    assert _attribute_problem(storage["989"], [{"valueId": "0", "name": "任意文本"}]) is None
    toy_measure = toy["4738"]
    assert toy_measure.control == "measure" and len(toy_measure.measureTemplates[0].modules) == 3
    assert measure_valid("11*22*22cm", toy_measure.measureTemplates)
    assert measure_valid("11×22×22mm", toy_measure.measureTemplates)
    assert not measure_valid("0*22*22cm", toy_measure.measureTemplates)
    assert not measure_valid("11*22*10001cm", toy_measure.measureTemplates)
    assert not measure_valid("11.22*22*22cm", toy_measure.measureTemplates)
    assert not measure_valid("11*22*22", toy_measure.measureTemplates)
    assert measure_valid("长11cm×宽5cm×高30cm", storage["1847"].measureTemplates)


def test_real_age_options_split_only_unambiguous_multi_values():
    fields = real_fields("1000001535")
    age = fields["2595"]
    assert age.control == "multi" and age.maxValues == 5 and age.allowCustom is False
    values = normalize_multi_values(age, [{"valueId": "0", "name": "3周岁-6周岁|6周岁-8周岁"}])
    assert values == [{"valueId": "64357", "name": "3周岁-6周岁"},
                      {"valueId": "64359", "name": "6周岁-8周岁"}]
    assert _attribute_problem(age, values) is None
    unknown = [{"valueId": "0", "name": "3周岁-6周岁|未知年龄"}]
    assert normalize_multi_values(age, unknown) == unknown
    assert _attribute_problem(age, values * 3) == "最多选5项"
    assert fields["810"].control == "multi" and fields["810"].allowCustom is True


def test_no_options_custom_multi_remains_a_multi_select():
    field = Attribute.model_validate(normalize_fields([{"id": "1", "label": "测试", "required": False,
        "additions": {"ui_type": "multi_select", "diy_type": 1}, "options": []}])[0])
    assert field.control == "multi" and field.allowCustom is True
    assert _attribute_problem(field, [{"valueId": "0", "name": "自定义一"},
                                      {"valueId": "0", "name": "自定义二"}]) is None


def test_multi_values_are_not_truncated_by_an_unrelated_fixed_limit():
    from app.modules.products.schemas import AttributeEdit
    from app.modules.products.source_attributes import source_attributes

    values = [{"valueId": "0", "name": f"自定义{index}"} for index in range(35)]
    attribute = AttributeEdit(id="1", name="自定义多选", values=values)
    entries = [{"k": attribute.name, "value_id": value.valueId, "value_name": value.name}
               for value in attribute.values]
    assert len(source_attributes({"1": entries}, [])[0]["valueItems"]) == 35
