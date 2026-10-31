from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.product_edit.models import CreateManualProduct, ProductDraft, SaveDraft
from app.modules.product_edit.normalize import draft_from_source, source_fingerprint


def example_source(platform="douyin"):
    return {"product_id": "3760269504500859111", "source_platform": platform,
            "title": "测试商品", "category_path": "家居/杯子"}


def example_payload():
    return {
        "goodsInfo": {"goodsName": "测试商品", "catId1": "123", "catId2": "456"},
        "spec_detail_value": {"value": [
            {"name": "颜色", "spec_values": [{"id": "black", "name": "黑色", "img_url": "https://example.test/black.jpg"},
                                              {"id": "white", "name": "白色"}]},
            {"name": "款式", "spec_values": [{"id": "long", "name": "长款"}, {"id": "short", "name": "短款"}]},
        ]},
        "goodsSkuInfo": {"spec_detail": {"value": [
            {"sku_id": "1234567890123456789", "spec_detail_ids": ["long", "black"], "price": "18.50", "stock_info": {"stock_num": 8}, "sku_status": True},
            {"sku_id": "1234567890123456790", "spec_detail_ids": ["white", "short"], "price": "20", "stock_info": {"stock_num": 0}, "sku_status": False},
            {"spec_detail_ids": ["black", "unknown"], "price": "21"},
        ]}},
        "category_properties_value": {"value": {"21": [{"k": "材质", "value_id": "9", "value_name": "塑料"}]}},
    }


def test_normalization_preserves_source_status_and_never_invents_combinations():
    images = [{"image_type": "main", "sort_order": 0, "source_url": "https://example.test/a.jpg", "rel_path": ""}]
    draft = draft_from_source(example_source(), [], images, example_payload())
    assert draft.categoryIds == ["123", "456"]
    assert draft.mainImages[0].url == "https://example.test/a.jpg"
    assert draft.imageDimensionId == draft.dimensions[0].id
    assert len(draft.skus) == 3
    assert draft.skus[0].sourceSkuId == "1234567890123456789"
    assert draft.skus[0].specValueIds == {"source-dimension-0": "source-value-0-0", "source-dimension-1": "source-value-1-0"}
    assert draft.skus[0].state == "active" and draft.skus[1].state == "unknown"
    assert draft.skus[0].sourceStatusRaw == "true" and draft.skus[1].sourceStatusRaw == "false"
    assert draft.skus[2].state == "unknown" and draft.skus[2].unmappedSpecIds == ["unknown"]
    assert draft.skus[2].stock is None
    assert draft.attributes[0].values[0].name == "塑料"


def test_non_douyin_source_category_is_not_mistaken_for_target_category():
    draft = draft_from_source(example_source("pinduoduo"), [], [], example_payload())
    assert draft.categoryIds == [] and draft.categoryPath == "" and draft.attributes == []


def test_fallback_skus_keep_exact_price_but_do_not_guess_spec_or_image():
    source_skus = [{"sku_id": "1234567890123456789", "sku_name": "白色短款", "current_price": Decimal("19.90")}]
    draft = draft_from_source(example_source(), source_skus, [], {})
    assert draft.skus[0].price == "19.90"
    assert draft.skus[0].sourceLabel == "白色短款"
    assert draft.skus[0].specValueIds == {} and draft.skus[0].state == "unknown"


def test_duplicate_spec_ids_do_not_get_guessed_and_source_fingerprint_is_stable():
    payload = example_payload()
    payload["spec_detail_value"]["value"][1]["spec_values"][0]["id"] = "black"
    draft = draft_from_source(example_source(), [], [], payload)
    assert "black" in draft.skus[0].unmappedSpecIds
    assert source_fingerprint({"b": 2, "a": 1}) == source_fingerprint({"a": 1, "b": 2})
    assert source_fingerprint({"a": 1}) != source_fingerprint({"a": 2})


def test_douyin_off_sale_requires_explicit_raw_status_and_placeholder_stock_is_not_real_stock():
    payload = example_payload()
    payload["goodsInfo"]["skuInfoMap"] = {"white_short": {"sku_status": "1"}}
    payload["goodsSkuInfo"]["spec_detail"]["value"][1]["stock_info"]["stock_num"] = 999
    draft = draft_from_source(example_source(), [], [], payload)
    assert draft.skus[1].state == "inactive"
    assert draft.skus[1].stock is None
    assert draft.skus[1].sourceStockRaw == "999" and draft.skus[1].sourceStockPlaceholder
    payload["goodsInfo"]["skuInfoMap"]["white_short"] = {}
    assert draft_from_source(example_source(), [], [], payload).skus[1].state == "unknown"


def test_composite_source_spec_ids_are_matched_only_when_unambiguous():
    payload = example_payload()
    payload["spec_detail_value"]["value"][0]["spec_values"][0]["id"] = "black_ink"
    payload["goodsSkuInfo"]["spec_detail"]["value"][0]["spec_detail_ids"] = ["ink", "long", "black"]
    draft = draft_from_source(example_source(), [], [], payload)
    assert draft.skus[0].specValueIds == {"source-dimension-0": "source-value-0-0", "source-dimension-1": "source-value-1-0"}
    assert draft.skus[0].unmappedSpecIds == []
    payload["spec_detail_value"]["value"][0]["spec_values"][1]["id"] = "black_ink"
    ambiguous = draft_from_source(example_source(), [], [], payload)
    assert ambiguous.skus[0].unmappedSpecIds


def pdd_payload():
    def sku(sku_id, color, style, on_sale, price, stock, image):
        return {"skuId": sku_id, "name": f"颜色：{color} / 款式：{style}",
                "specs": [{"keyId": "100", "key": "颜色", "valueId": "11" if color == "黑色" else "12", "value": color},
                          {"keyId": "200", "key": "款式", "valueId": "21" if style == "长款" else "22", "value": style}],
                "onSale": on_sale, "stock": stock, "groupPrice": price, "imageUrl": image}
    return {"schemaVersion": "pdd-package-v1", "sourcePlatform": "pinduoduo",
            "product": {"categoryIds": ["111", "222"], "properties": [{"propertyId": "7", "key": "材质", "values": ["塑料"]}]},
            "skus": [sku("1234567890123456789", "黑色", "长款", True, 19.9, 8, "https://example.test/black.jpg"),
                     sku("1234567890123456790", "白色", "短款", False, 20, 0, "https://example.test/white.jpg")],
            "images": {"main": [{"url": "https://example.test/main.jpg"}], "detail": [{"url": "https://example.test/detail.jpg"}]}}


def test_pdd_specs_keep_identity_price_and_source_images_without_guessing_image_axis():
    draft = draft_from_source(example_source("pinduoduo"), [], [], pdd_payload())
    assert draft.categoryIds == [] and draft.categoryPath == ""
    assert draft.sourceCategoryIds == ["111", "222"]
    assert draft.sourceAttributes[0].name == "材质" and draft.sourceAttributes[0].values[0].name == "塑料"
    assert [axis.name for axis in draft.dimensions] == ["颜色", "款式"]
    assert len(draft.skus) == 2 and draft.skus[0].sourceSkuId == "1234567890123456789"
    assert len(draft.skus[0].specValueIds) == 2 and draft.skus[0].state == "active"
    assert draft.skus[0].price == "19.9" and draft.skus[0].stock == 8
    assert draft.skus[1].state == "unknown" and draft.skus[1].sourceStatusRaw == "false"
    assert draft.skus[1].stock is None and draft.skus[1].sourceStockUnconfirmed
    assert draft.skus[1].sourceStockRaw == "0"
    assert draft.skus[1].sourceImageUrl == "https://example.test/white.jpg"
    assert draft.imageDimensionId is None and not draft.dimensions[0].values[0].imageUrl
    assert draft.mainImages[0].url == "https://example.test/main.jpg"
    assert draft.detailImages[0].url == "https://example.test/detail.jpg"


def test_pdd_single_axis_can_map_images_but_conflicts_and_missing_ids_remain_safe():
    payload = pdd_payload()
    for sku in payload["skus"]:
        sku["specs"] = sku["specs"][:1]
    payload["skus"][1]["specs"][0]["keyId"] = ""
    draft = draft_from_source(example_source("pinduoduo"), [], [], payload)
    assert len(draft.dimensions) == 1 and draft.imageDimensionId == draft.dimensions[0].id
    assert draft.dimensions[0].values[1].imageUrl == "https://example.test/white.jpg"
    assert draft.skus[1].unmappedSpecIds == []
    conflicting = pdd_payload()
    conflicting["skus"][1]["specs"][0]["valueId"] = "11"
    conflict_draft = draft_from_source(example_source("pinduoduo"), [], [], conflicting)
    assert all(row.unmappedSpecIds for row in conflict_draft.skus)


def test_pdd_zero_price_from_converter_needs_confirmation():
    payload = pdd_payload()
    payload["skus"][0]["groupPrice"] = 0
    sku = draft_from_source(example_source("pinduoduo"), [], [], payload).skus[0]
    assert sku.price is None and sku.sourcePriceUnconfirmed and sku.sourcePriceRaw == "0"


def test_only_first_dimension_can_be_enabled_for_spec_images_and_duplicate_ids_rejected():
    with pytest.raises(ValidationError, match="第一组规格"):
        ProductDraft.model_validate({"dimensions": [{"id": "color"}, {"id": "style"}], "imageDimensionId": "style"})
    with pytest.raises(ValidationError, match="规格值标识重复"):
        ProductDraft.model_validate({"dimensions": [{"id": "color", "values": [{"id": "same"}]},
                                                      {"id": "style", "values": [{"id": "same"}]}]})


def test_long_original_title_can_be_loaded_but_cannot_be_saved_until_shortened():
    source = example_source()
    source["title"] = "商" * 31
    draft = draft_from_source(source, [], [], {})
    assert draft.title == "商" * 31
    with pytest.raises(ValidationError, match="60"):
        SaveDraft(expectedRevision=0, sourceFingerprint="a" * 64, draft=draft)
    with pytest.raises(ValidationError, match="60"):
        CreateManualProduct(title="A" * 61)
    draft.title = "商" * 30
    assert SaveDraft(expectedRevision=0, sourceFingerprint="a" * 64, draft=draft).draft.title == draft.title
