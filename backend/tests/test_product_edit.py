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


def test_normalization_preserves_explicit_sku_states_and_never_invents_missing_combinations():
    images = [{"image_type": "main", "sort_order": 0, "source_url": "https://example.test/a.jpg", "rel_path": ""}]
    draft = draft_from_source(example_source(), [], images, example_payload())
    assert draft.categoryIds == ["123", "456"]
    assert draft.mainImages[0].url == "https://example.test/a.jpg"
    assert draft.imageDimensionId == draft.dimensions[0].id
    assert len(draft.skus) == 3
    assert draft.skus[0].sourceSkuId == "1234567890123456789"
    assert draft.skus[0].specValueIds == {"source-dimension-0": "source-value-0-0", "source-dimension-1": "source-value-1-0"}
    assert draft.skus[0].state == "active" and draft.skus[1].state == "inactive"
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
