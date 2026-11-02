"""Make narrowly scoped changes to a database package without discarding source fields."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json

from .errors import ProductRequestError
from .schemas import ProductEdit


def _mapping(value, message: str) -> dict:
    if not isinstance(value, dict):
        raise ProductRequestError(message)
    return value


def _url(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        urls = value.get("url_list")
        return (urls[0] if isinstance(urls, list) and urls else "") or value.get("url", "")
    return ""


def _ordered_images(original, urls: list[str], make):
    existing = {_url(value): value for value in original if _url(value)} if isinstance(original, list) else {}
    return [deepcopy(existing[url]) if url in existing else make(url) for url in urls]


def _edit_skus(data: dict, changes) -> None:
    info = _mapping(data.get("goodsSkuInfo"), "商品缺少 SKU 信息")
    detail = _mapping(info.get("spec_detail"), "商品缺少 SKU 组合")
    rows = detail.get("value")
    sku_map = _mapping(_mapping(data.get("goodsInfo"), "商品信息无效").get("skuInfoMap"), "商品缺少 SKU 来源映射")
    if not isinstance(rows, list):
        raise ProductRequestError("SKU 组合格式无效")
    for change in changes:
        key = "_".join(change.specIds)
        matches = [row for row in rows if isinstance(row, dict) and isinstance(row.get("spec_detail_ids"), list) and
                   [str(value) for value in row["spec_detail_ids"]] == change.specIds]
        original = sku_map.get(key)
        if len(matches) != 1 or not isinstance(original, dict):
            raise ProductRequestError("SKU 与原数据包不能唯一对应，请刷新后重试")
        row = matches[0]
        if change.delete:
            rows.remove(row)
            del sku_map[key]
            continue
        if change.price is not None:
            amount = format(change.price.quantize(Decimal("0.01")), "f")
            row["price"] = amount
            raw = original.get("extra_business_info", "{}")
            try:
                business = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
            except ValueError:
                raise ProductRequestError("SKU 来源价格格式无效，无法安全修改") from None
            if not isinstance(business, dict):
                raise ProductRequestError("SKU 来源价格格式无效，无法安全修改")
            for field in ("first_price", "second_price"):
                price = business.get(field)
                if not isinstance(price, dict):
                    price = {}
                price["left_price_num"] = int(change.price * 100)
                business[field] = price
            original["extra_business_info"] = json.dumps(business, ensure_ascii=False, separators=(",", ":")) if isinstance(raw, str) else business
            original["aria_label_price"] = f"¥{amount}"
        if change.stock is not None:
            stock = row.setdefault("stock_info", {})
            _mapping(stock, "SKU 库存格式无效")["stock_num"] = change.stock
        if change.enabled is not None:
            row["sku_status"] = change.enabled
        if change.merchantCode is not None:
            row["merchant_code"] = change.merchantCode

    prices = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            value = Decimal(str(row.get("price", "")))
            if value.is_finite() and value >= 0:
                prices.append((row, value))
        except InvalidOperation:
            continue
    detail["myPriceRange"] = f"{min(value for _, value in prices)}-{max(value for _, value in prices)}" if prices else ""
    min_by_spec = {}
    for row, price in prices:
        for spec_id in row.get("spec_detail_ids", []) if isinstance(row.get("spec_detail_ids"), list) else []:
            key = str(spec_id)
            min_by_spec[key] = min(min_by_spec.get(key, price), price)
    for group in info.get("sku_detail", []):
        if not isinstance(group, dict):
            continue
        for item in group.get("spec_item_list", []):
            if isinstance(item, dict) and str(item.get("spec_item_id")) in min_by_spec:
                item["price"] = str(min_by_spec[str(item["spec_item_id"])])
    spec_block = data.get("spec_detail_value")
    for group in spec_block.get("value", []) if isinstance(spec_block, dict) else []:
        if not isinstance(group, dict):
            continue
        for item in group.get("spec_values", []):
            if isinstance(item, dict) and str(item.get("id")) in min_by_spec:
                item["_price"] = str(min_by_spec[str(item["id"])])


def apply_edit(source: dict, platform: str, edit: ProductEdit) -> dict:
    """Return a modified copy; reject shapes we cannot faithfully translate."""
    data = deepcopy(_mapping(source, "商品数据包格式无效"))
    if platform == "douyin":
        goods = _mapping(data.get("goodsInfo"), "抖音商品数据包缺少商品信息")
        if edit.skus is not None:
            _edit_skus(data, edit.skus)
        if edit.title is not None:
            goods["goodsName"] = edit.title
        if edit.mainImages is not None:
            goods["goodsImageList"] = list(edit.mainImages)
        if edit.detailImages is not None:
            details = _mapping(data.get("goodsDetailInfo"), "商品数据包缺少详情图片信息")
            details["detail_imgs"] = _ordered_images(details.get("detail_imgs"), edit.detailImages,
                                                      lambda url: {"url_list": [url]})
            previous = details.get("detail_imgs_new")
            old_new = {_url(item.get("image")): item for item in previous if isinstance(item, dict) and _url(item.get("image"))} if isinstance(previous, list) else {}
            details["detail_imgs_new"] = [deepcopy(old_new[url]) if url in old_new else
                {"image": deepcopy(image), "pic_type": "pic"}
                for url, image in zip(edit.detailImages, details["detail_imgs"], strict=True)]
        if edit.specImages is not None:
            value_groups = _mapping(data.get("spec_detail_value"), "商品缺少规格图片信息").get("value")
            sku_groups = _mapping(data.get("goodsSkuInfo"), "商品缺少销售规格").get("sku_detail")
            if not isinstance(value_groups, list) or not value_groups or not isinstance(sku_groups, list) or not sku_groups:
                raise ProductRequestError("商品缺少第一组销售规格")
            value_items = _mapping(value_groups[0], "商品规格格式无效").get("spec_values")
            sku_items = _mapping(sku_groups[0], "商品规格格式无效").get("spec_item_list")
            if not isinstance(value_items, list) or not isinstance(sku_items, list):
                raise ProductRequestError("商品规格格式无效")
            for item in edit.specImages:
                matches = [value for value in value_items if isinstance(value, dict) and str(value.get("id", "")) == item.specId]
                linked = [value for value in sku_items if isinstance(value, dict) and str(value.get("spec_item_id", "")) == item.specId]
                if len(matches) != 1 or len(linked) != 1:
                    raise ProductRequestError("规格图片与原数据包不能唯一对应，请刷新后重试")
                matches[0]["img_url"] = item.url
                linked[0]["big_pic"] = item.url
        if edit.category is not None:
            previous_id = next((str(goods.get(f"catId{level}")) for level in range(4, 0, -1)
                                if goods.get(f"catId{level}") not in (None, "", "0", 0)), "")
            for level in range(1, 5):
                goods[f"catId{level}"] = edit.category[level - 1].id if level <= len(edit.category) else "0"
            if previous_id != edit.category[-1].id:
                # Values from a different category must not masquerade as valid target properties.
                data["category_properties_value"] = {"value": {}}
                details = data.get("goodsDetailInfo")
                if isinstance(details, dict):
                    details["product_format"] = []
        if edit.attributes is not None:
            block = data.setdefault("category_properties_value", {"value": {}})
            values = _mapping(_mapping(block, "商品属性格式无效").setdefault("value", {}), "商品属性格式无效")
            edited_ids = {item.id for item in edit.attributes}
            for item in edit.attributes:
                if item.values:
                    values[item.id] = [{"diy_type": 1, "k": item.name, "value_id": value.valueId,
                                        "value_name": value.name} for value in item.values]
                else:
                    values.pop(item.id, None)
            details = data.get("goodsDetailInfo")
            if isinstance(details, dict) and isinstance(details.get("product_format"), list):
                for group in details["product_format"]:
                    if isinstance(group, dict) and isinstance(group.get("format"), list):
                        group["format"] = [item for item in group["format"] if not isinstance(item, dict)
                                           or str(item.get("property_id", "")) not in edited_ids]
    elif platform in {"pinduoduo", "pdd"}:
        product = _mapping(data.get("product"), "拼多多商品数据包缺少商品信息")
        if edit.category is not None or edit.attributes is not None or edit.specImages is not None or edit.skus is not None:
            raise ProductRequestError("拼多多数据包的抖店类目转换尚未接入")
        if edit.title is not None:
            product["title"] = edit.title
        if edit.mainImages is not None or edit.detailImages is not None:
            images = _mapping(data.get("images"), "商品数据包缺少图片信息")
            for kind, urls in (("main", edit.mainImages), ("detail", edit.detailImages)):
                if urls is not None:
                    images[kind] = _ordered_images(images.get(kind), urls, lambda url: {"url": url})
    else:
        raise ProductRequestError("暂不支持编辑该来源平台的数据包")
    return data
