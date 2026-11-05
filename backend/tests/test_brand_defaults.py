from app.modules.category_lookup.api import Attribute, Option
from app.modules.products.brand_defaults import no_brand_selection


def test_real_brand_field_resolves_platform_no_brand_id():
    field = Attribute(id="1687", label="品牌", required=True,
        options=[Option(label="无品牌", value="596120136"), Option(label="HP/惠普", value="2065951823")],
        control="single", allowCustom=False, ruleStatus="confirmed")
    assert no_brand_selection([field]) == {
        "fieldId": "1687", "fieldName": "品牌",
        "valueId": "596120136", "valueName": "无品牌",
    }


def test_no_brand_is_not_fabricated_when_rule_or_option_is_ambiguous():
    unknown = Attribute(id="1687", label="品牌", required=True,
        options=[Option(label="无品牌", value="596120136")], control="unknown",
        allowCustom=None, ruleStatus="unknown")
    assert no_brand_selection([unknown]) is None
    confirmed = unknown.model_copy(update={"control": "single", "allowCustom": False,
                                           "ruleStatus": "confirmed"})
    assert no_brand_selection([confirmed, confirmed.model_copy(update={"id": "other"})]) is None
