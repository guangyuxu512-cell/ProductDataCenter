import pytest
from pydantic import ValidationError

from app.modules.products.editing import apply_edit
from app.modules.products.manual import manual_package
from app.modules.products.schemas import ManualProductCreate, ProductEdit


def test_manual_draft_uses_editable_rpa_package_shape():
    package, sku_id = manual_package("手动商品")
    spec = package["spec_detail_value"]["value"][0]["spec_values"][0]["id"]
    assert package["goodsInfo"]["skuInfoMap"][spec]["_local_sku_key"] == sku_id
    assert package["goodsSkuInfo"]["spec_detail"]["value"][0]["sku_status"] is False
    assert package["goodsSkuInfo"]["spec_detail"]["value"][0]["price"] == ""
    edited = apply_edit(package, "douyin", ProductEdit(expectedVersion="a" * 64,
        category=[{"id": "100", "name": "家居"}],
        skus=[{"specIds": [spec], "price": "9.90", "stock": 5, "enabled": True}]))
    assert edited["goodsInfo"]["catId1"] == "100"
    sku = edited["goodsSkuInfo"]["spec_detail"]["value"][0]
    assert sku["price"] == "9.90" and sku["stock_info"]["stock_num"] == 5 and sku["sku_status"] is True


def test_manual_product_title_uses_editor_length_rules():
    assert ManualProductCreate(title="  新商品  ").title == "新商品"
    with pytest.raises(ValidationError):
        ManualProductCreate(title="商" * 31)


def test_manual_creation_requires_matching_seed_and_title():
    edit = ProductEdit(expectedVersion="0" * 64, title="新商品")
    with pytest.raises(ValidationError):
        ManualProductCreate(title="新商品", edit=edit)
    with pytest.raises(ValidationError):
        ManualProductCreate(title="其他商品", draftSeed="a" * 32, edit=edit)
    body = ManualProductCreate(title="新商品", draftSeed="a" * 32, edit=edit)
    package, sku_id = manual_package(body.title, body.draftSeed)
    assert package["spec_detail_value"]["value"][0]["spec_values"][0]["id"] == "local-" + "a" * 32 + "-spec"
    assert sku_id == "local-" + "a" * 32 + "-sku"
