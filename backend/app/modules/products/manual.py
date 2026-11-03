"""Construct an editable draft in the package shape consumed by the RPA."""

from uuid import uuid4


def manual_package(title: str) -> tuple[dict, str]:
    spec_id = "local-" + uuid4().hex
    sku_id = "local-" + uuid4().hex
    package = {
        "goodsInfo": {"goodsName": title, "goodsImageList": [], "skuInfoMap": {
            spec_id: {"_local_sku_key": sku_id},
        }, "catId1": "0", "catId2": "0", "catId3": "0", "catId4": "0"},
        "goodsDetailInfo": {"detail_imgs": [], "product_format": []},
        "category_properties_value": {"value": {}},
        "spec_detail_value": {"value": [{"name": "规格", "spec_values": [
            {"id": spec_id, "name": "默认", "img_url": ""},
        ]}]},
        "goodsSkuInfo": {"sku_detail": [{"name": "规格", "spec_item_list": [
            {"spec_item_id": spec_id, "name": "默认", "big_pic": ""},
        ]}], "spec_detail": {"value": [{"spec_detail_ids": [spec_id], "price": "",
                                        "stock_info": {"stock_num": None}, "sku_status": False}]}},
    }
    return package, sku_id
