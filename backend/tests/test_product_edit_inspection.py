import hashlib
import json

from app.modules.product_edit.inspection import build_candidate, inspect_draft
from app.modules.product_edit.models import ProductDraft


SOURCE_ID = "3841753226848370763"


def sample_draft():
    return ProductDraft.model_validate({
        "title": "测试商品", "categoryIds": ["11", "22", "33"],
        "mainImages": [{"id": "m1", "url": "https://images.example.test/main.jpg"}],
        "detailImages": [{"id": "d1", "url": "https://images.example.test/detail.jpg"}],
        "attributes": [{"id": "a1", "name": "材质", "values": [{"id": "v1", "name": "棉"}]}],
        "imageDimensionId": "color",
        "dimensions": [
            {"id": "color", "name": "颜色", "values": [
                {"id": "black", "name": "黑色", "imageUrl": "https://images.example.test/black.jpg"},
                {"id": "white", "name": "白色", "imageUrl": "https://images.example.test/white.jpg"}]},
            {"id": "style", "name": "款式", "values": [
                {"id": "long", "name": "长款"}, {"id": "short", "name": "短款"}]}],
        "skus": [{"id": f"{color}-{style}", "specValueIds": {"color": color, "style": style},
                  "price": "12.50", "stock": 4, "state": "inactive" if color == "white" and style == "short" else "active"}
                 for color in ("black", "white") for style in ("long", "short")],
    })


def check(draft, platform="douyin", source_id=SOURCE_ID, changed=False):
    return inspect_draft(draft, product_id=SOURCE_ID, source_platform=platform,
                         source_product_id=source_id, source_changed=changed)


def codes(result):
    return {issue.code for issue in result.issues}


def test_candidate_preserves_sku_states_and_is_never_published():
    draft = sample_draft()
    before = draft.model_dump_json()
    result = check(draft)
    payload_bytes = build_candidate(draft, SOURCE_ID)
    payload = json.loads(payload_bytes)
    assert result.localStatus == "passed" and result.rpaStatus == "compatible"
    assert result.platformStatus == "not_checked" and result.canPublish is False
    assert result.candidateSha256 == hashlib.sha256(payload_bytes).hexdigest()
    assert payload_bytes == build_candidate(draft, SOURCE_ID)
    assert payload["goodsInfo"]["goodsId"] == SOURCE_ID
    assert [row["sku_status"] for row in payload["goodsSkuInfo"]["spec_detail"]["value"]] == [True, True, True, False]
    assert draft.model_dump_json() == before
    draft.mainImages.pop()
    assert "MAIN_IMAGE_REQUIRED" in codes(check(draft))
    assert check(draft).candidateSha256 is None


def test_missing_combination_does_not_silently_become_inactive():
    draft = sample_draft()
    draft.skus.pop()
    result = check(draft)
    assert "SKU_COMBINATIONS_UNCONFIRMED" in codes(result)
    assert result.rpaStatus == "blocked" and result.candidateSha256 is None


def test_unknown_stock_state_and_invalid_urls_are_explained():
    draft = sample_draft()
    draft.title = ""
    draft.categoryIds = []
    draft.mainImages[0].url = "http://example.test/image.jpg"
    draft.skus[0].stock = None
    draft.skus[0].state = "unknown"
    draft.skus[0].merchantCode = "ERP-1"
    result = check(draft, changed=True)
    assert codes(result) >= {"TITLE_INVALID", "TARGET_CATEGORY_REQUIRED", "IMAGE_UNAVAILABLE_TO_RPA",
                             "SKU_STOCK_REQUIRED", "SKU_STATE_UNCONFIRMED", "RPA_MERCHANT_CODE_UNSUPPORTED", "SOURCE_CHANGED"}
    assert result.rpaStatus == "blocked" and result.candidateSha256 is None


def test_rpa_limits_and_image_integrity():
    draft = sample_draft()
    draft.mainImages.append(draft.mainImages[0].model_copy(update={"id": "m2"}))
    draft.dimensions[0].values[0].imageUrl = ""
    result = check(draft, platform="manual", source_id=None)
    assert codes(result) >= {"DUPLICATE_IMAGE", "SPEC_IMAGES_INCOMPLETE", "RPA_SOURCE_UNSUPPORTED"}
    draft = sample_draft()
    for invalid in ("https://user:pass@example.test/a", "https://example.test:99999/a", "https://exa mple.test/a"):
        draft.mainImages[0].url = invalid
        assert "IMAGE_UNAVAILABLE_TO_RPA" in codes(check(draft))
