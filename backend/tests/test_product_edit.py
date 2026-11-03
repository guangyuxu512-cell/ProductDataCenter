from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.modules.products.editing import apply_edit
from app.modules.products.errors import ProductRequestError
from app.modules.products.repository import _spec_image_values
from app.modules.products.schemas import ProductEdit


VERSION = "a" * 64


def test_spec_image_falls_back_only_to_the_matching_unambiguous_id():
    groups = [{"spec_values": [{"id": "11", "name": "黑色", "img_url": ""},
                               {"id": "12", "name": "白色", "img_url": ""}]}]
    sku_groups = [{"spec_item_list": [{"spec_item_id": "11", "small_pic": "https://example.test/black"},
                                      {"spec_item_id": "12", "big_pic": "https://example.test/a"},
                                      {"spec_item_id": "12", "big_pic": "https://example.test/b"}]}]
    assert _spec_image_values(groups, sku_groups, 0) == [
        {"id": "11", "name": "黑色", "url": "https://example.test/black"},
        {"id": "12", "name": "白色", "url": ""},
    ]


@pytest.fixture
def douyin():
    return {
        "goodsId": "1234567890123456789", "untouched": {"sku": "kept"},
        "goodsInfo": {"goodsName": "旧标题", "catId1": "1", "catId2": "2", "catId3": "0", "catId4": "0",
                      "goodsImageList": ["https://example.test/a", "https://example.test/b"],
                      "skuInfoMap": {"11_22": {"sku_id": "1234567890123456788"}}},
        "category_properties_value": {"value": {"5": [{"k": "材质", "value_name": "棉"}]}},
        "goodsDetailInfo": {"detail_imgs": [{"url_list": ["https://example.test/c"], "width": 1200}],
                            "detail_imgs_new": [{"image": {"url_list": ["https://example.test/c"]}, "pic_type": "pic"}],
                            "product_format": [{"format": [{"property_id": "5", "name": "材质"}]}]},
        "goodsSkuInfo": {"spec_detail": {"value": [{"spec_detail_ids": ["11", "22"], "sku_status": False}]}},
    }


def test_edit_retains_skus_and_unknown_fields_and_keeps_image_metadata(douyin):
    original = deepcopy(douyin)
    edit = ProductEdit(expectedVersion=VERSION, title="新的商品", mainImages=["https://example.test/b"],
                       detailImages=["https://example.test/c", "https://example.test/new"])
    result = apply_edit(douyin, "douyin", edit)
    assert douyin == original
    assert result["goodsInfo"]["goodsName"] == "新的商品"
    assert result["goodsInfo"]["goodsImageList"] == ["https://example.test/b"]
    assert result["goodsDetailInfo"]["detail_imgs"][0]["width"] == 1200
    assert result["goodsDetailInfo"]["detail_imgs_new"][1]["image"]["url_list"] == ["https://example.test/new"]
    assert result["goodsSkuInfo"] == original["goodsSkuInfo"]
    assert result["goodsInfo"]["skuInfoMap"] == original["goodsInfo"]["skuInfoMap"]
    assert result["untouched"] == original["untouched"]


def test_change_category_clears_old_properties_and_saves_new_values(douyin):
    edit = ProductEdit(expectedVersion=VERSION, category=[{"id": "9", "name": "新类目"}],
                       attributes=[{"id": "8", "name": "品牌", "values": [{"valueId": "42", "name": "无品牌"}]}])
    result = apply_edit(douyin, "douyin", edit)
    assert [result["goodsInfo"][f"catId{i}"] for i in range(1, 5)] == ["9", "0", "0", "0"]
    assert list(result["category_properties_value"]["value"]) == ["8"]
    assert result["category_properties_value"]["value"]["8"][0]["value_id"] == "42"
    assert result["goodsDetailInfo"]["product_format"] == []


def test_pdd_title_and_images_preserve_source_shape():
    package = {"product": {"title": "旧"}, "images": {"main": [{"url": "https://example.test/a", "tag": 1}], "detail": []}, "skus": [{"onSale": False}]}
    edit = ProductEdit(expectedVersion=VERSION, title="新", mainImages=["https://example.test/a"])
    result = apply_edit(package, "pinduoduo", edit)
    assert result["product"]["title"] == "新"
    assert result["images"]["main"][0]["tag"] == 1
    assert result["skus"][0]["onSale"] is False
    with pytest.raises(ProductRequestError):
        apply_edit(package, "pinduoduo", ProductEdit(expectedVersion=VERSION, category=[{"id": "1", "name": "类目"}]))


def test_invalid_title_and_image_are_rejected():
    with pytest.raises(ValidationError):
        ProductEdit(expectedVersion=VERSION, title="长" * 31)
    with pytest.raises(ValidationError):
        ProductEdit(expectedVersion=VERSION, mainImages=["file:///etc/passwd"])


def test_spec_image_changes_both_package_representations_and_preserves_off_sale(douyin):
    douyin["spec_detail_value"] = {"value": [{"name": "颜色", "spec_values": [{"id": "11", "name": "黑色", "img_url": "https://example.test/old"}]}]}
    douyin["goodsSkuInfo"]["sku_detail"] = [{"name": "颜色", "spec_item_list": [{"spec_item_id": "11", "name": "黑色", "big_pic": "https://example.test/old"}]}]
    edit = ProductEdit(expectedVersion=VERSION, specImages=[{"specId": "11", "url": "https://example.test/new"}])
    result = apply_edit(douyin, "douyin", edit)
    assert result["spec_detail_value"]["value"][0]["spec_values"][0]["img_url"] == "https://example.test/new"
    assert result["goodsSkuInfo"]["sku_detail"][0]["spec_item_list"][0]["big_pic"] == "https://example.test/new"
    assert result["goodsSkuInfo"]["spec_detail"]["value"][0]["sku_status"] is False
    with pytest.raises(ProductRequestError):
        apply_edit(douyin, "douyin", ProductEdit(expectedVersion=VERSION, specImages=[{"specId": "unknown", "url": ""}]))


def test_sku_edit_and_deletion_do_not_recreate_missing_or_change_off_sale_variants(douyin):
    douyin["goodsInfo"]["skuInfoMap"] = {
        "11_21": {"sku_id": "1001", "extra_business_info": '{"first_price":{"left_price_num":1200}}'},
        "11_22": {"sku_id": "1002", "extra_business_info": '{"first_price":{"left_price_num":1500}}'},
        "12_22": {"sku_id": "1003", "extra_business_info": '{"first_price":{"left_price_num":1600}}'},
    }
    douyin["goodsSkuInfo"]["spec_detail"]["value"] = [
        {"spec_detail_ids": ["11", "21"], "price": "12", "sku_status": True, "stock_info": {"stock_num": 5}},
        {"spec_detail_ids": ["11", "22"], "price": "15", "sku_status": True, "stock_info": {"stock_num": 8}},
        {"spec_detail_ids": ["12", "22"], "price": "16", "sku_status": False, "stock_info": {"stock_num": 0}},
    ]
    edit = ProductEdit(expectedVersion=VERSION, skus=[{"specIds": ["11", "21"], "price": "19.90", "stock": 6},
        {"specIds": ["12", "22"], "merchantCode": "white-short"}])
    result = apply_edit(douyin, "douyin", edit)
    rows = result["goodsSkuInfo"]["spec_detail"]["value"]
    assert rows[0]["price"] == "19.90" and rows[0]["stock_info"]["stock_num"] == 6
    assert rows[2]["sku_status"] is False and rows[2]["merchant_code"] == "white-short"
    assert len(rows) == 3 and "12_21" not in result["goodsInfo"]["skuInfoMap"]
    assert '1990' in result["goodsInfo"]["skuInfoMap"]["11_21"]["extra_business_info"]
    deleted = apply_edit(result, "douyin", ProductEdit(expectedVersion=VERSION, skus=[{"specIds": ["12", "22"], "delete": True}]))
    assert len(deleted["goodsSkuInfo"]["spec_detail"]["value"]) == 2
    assert "12_22" not in deleted["goodsInfo"]["skuInfoMap"]
    assert all(row["sku_status"] is True for row in deleted["goodsSkuInfo"]["spec_detail"]["value"])


def test_move_image_group_keeps_existing_combinations_and_updates_package(douyin):
    douyin["goodsInfo"]["skuInfoMap"] = {
        "11_21": {"sku_id": "1001"}, "11_22": {"sku_id": "1002"}, "12_22": {"sku_id": "1003"},
    }
    douyin["_source_sku_prices"] = {"12_22": {"first_price": 1600}}
    douyin["goodsSkuInfo"]["spec_detail"]["value"] = [
        {"spec_detail_ids": ["11", "21"], "sku_status": True},
        {"spec_detail_ids": ["11", "22"], "sku_status": True},
        {"spec_detail_ids": ["12", "22"], "sku_status": False},
    ]
    douyin["goodsSkuInfo"]["sku_detail"] = [
        {"name": "颜色", "spec_index": 0, "spec_item_list": [
            {"spec_item_id": "11", "name": "黑色", "big_pic": "https://example.test/black", "small_pic": "https://example.test/black-small"},
            {"spec_item_id": "12", "name": "白色", "big_pic": ""}]},
        {"name": "款式", "spec_index": 1, "spec_item_list": [
            {"spec_item_id": "21", "name": "长款", "big_pic": ""},
            {"spec_item_id": "22", "name": "短款", "big_pic": ""}]},
    ]
    douyin["spec_detail_value"] = {"value": [
        {"name": "颜色", "spec_values": [{"id": "11", "name": "黑色", "img_url": "https://example.test/black"},
                                            {"id": "12", "name": "白色", "img_url": ""}]},
        {"name": "款式", "spec_values": [{"id": "21", "name": "长款", "img_url": ""},
                                            {"id": "22", "name": "短款", "img_url": ""}]},
    ]}
    original = deepcopy(douyin)
    result = apply_edit(douyin, "douyin", ProductEdit(expectedVersion=VERSION, specImageGroupIndex=1,
        specImages=[{"specId": "21", "url": "https://example.test/long"}],
        skus=[{"specIds": ["12", "22"], "stock": 3}]))
    assert douyin == original
    assert [group["name"] for group in result["goodsSkuInfo"]["sku_detail"]] == ["款式", "颜色"]
    assert [group["spec_index"] for group in result["goodsSkuInfo"]["sku_detail"]] == [0, 1]
    assert result["goodsSkuInfo"]["sku_detail"][0]["spec_item_list"][0]["big_pic"] == "https://example.test/long"
    assert result["goodsSkuInfo"]["sku_detail"][1]["spec_item_list"][0]["small_pic"] == ""
    assert result["spec_detail_value"]["value"][1]["spec_values"][0]["img_url"] == ""
    rows = result["goodsSkuInfo"]["spec_detail"]["value"]
    assert [row["spec_detail_ids"] for row in rows] == [["21", "11"], ["22", "11"], ["22", "12"]]
    assert rows[-1]["sku_status"] is False and rows[-1]["stock_info"]["stock_num"] == 3
    assert set(result["goodsInfo"]["skuInfoMap"]) == {"21_11", "22_11", "22_12"}
    assert result["_source_sku_prices"] == {"22_12": {"first_price": 1600}}


def test_move_image_group_rejects_ambiguous_sku_without_changing_source(douyin):
    douyin["spec_detail_value"] = {"value": [
        {"name": "颜色", "spec_values": [{"id": "11", "name": "黑色"}]},
        {"name": "款式", "spec_values": [{"id": "22", "name": "短款"}]},
    ]}
    douyin["goodsSkuInfo"]["sku_detail"] = [
        {"name": "颜色", "spec_item_list": [{"spec_item_id": "11"}]},
        {"name": "款式", "spec_item_list": [{"spec_item_id": "22"}]},
    ]
    douyin["goodsInfo"]["skuInfoMap"]["11_999"] = {"sku_id": "bad"}
    original = deepcopy(douyin)
    with pytest.raises(ProductRequestError):
        apply_edit(douyin, "douyin", ProductEdit(expectedVersion=VERSION, specImageGroupIndex=1))
    assert douyin == original
