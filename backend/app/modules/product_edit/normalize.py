"""将采集数据读取为可编辑草稿，不改写采集数据或猜测缺失的 SKU 状态。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from urllib.parse import quote

from .models import ProductDraft


def source_fingerprint(payload) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _text(value) -> str:
    return str(value).strip() if isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool) else ""


def _image(value) -> str:
    if isinstance(value, str):
        return value.strip()
    item = _dict(value)
    for candidate in (item.get("url"), item.get("img_url"), item.get("big_pic"),
                      item.get("small_pic"), *_list(item.get("url_list"))):
        found = _image(candidate) if isinstance(candidate, (str, dict)) else ""
        if found:
            return found
    return ""


def _price(value) -> str | None:
    result = _text(value)
    return result if re.fullmatch(r"\d{1,10}(?:\.\d{1,2})?", result, re.ASCII) else None


def _stock(value) -> int | None:
    result = _text(value)
    if not re.fullmatch(r"\d{1,10}", result, re.ASCII):
        return None
    number = int(result)
    return number if number <= 2_147_483_647 else None


def draft_from_source(product: dict, skus: list[dict], images: list[dict], payload) -> ProductDraft:
    payload = _dict(payload)
    goods = _dict(payload.get("goodsInfo"))
    is_douyin = product.get("source_platform") == "douyin"
    source_id = _text(product.get("product_id"))

    def image_items(kind: str):
        result = []
        for image in images:
            if image.get("image_type") != kind:
                continue
            position = image["sort_order"]
            url = _text(image.get("source_url"))
            if not url and image.get("rel_path"):
                url = f"/api/v1/products/{quote(source_id, safe='')}/images/{kind}/{position}"
            result.append({"id": f"{kind}-{position}", "url": url})
        return result

    raw_axes = _list(_dict(payload.get("spec_detail_value")).get("value"))
    dimensions, mapped_values = [], []
    for axis_index, raw_axis in enumerate(raw_axes):
        axis = _dict(raw_axis)
        dimension_id = f"source-dimension-{axis_index}"
        values = []
        for value_index, raw_value in enumerate(_list(axis.get("spec_values"))):
            value = _dict(raw_value)
            original_id = _text(value.get("id"))
            value_id = f"source-value-{axis_index}-{value_index}"
            values.append({"id": value_id, "sourceValueId": original_id or None,
                           "name": _text(value.get("name")), "imageUrl": _image(value.get("img_url"))})
            if original_id:
                mapped_values.append((original_id, dimension_id, value_id))
        dimensions.append({"id": dimension_id, "name": _text(axis.get("name")), "values": values})

    counts = Counter(item[0] for item in mapped_values)
    unambiguous = {original: (dimension, value) for original, dimension, value in mapped_values
                   if counts[original] == 1}
    raw_skus = _list(_dict(_dict(payload.get("goodsSkuInfo")).get("spec_detail")).get("value"))
    draft_skus = []
    for index, raw_sku in enumerate(raw_skus):
        sku = _dict(raw_sku)
        mappings, unmapped = {}, []
        for value_id in _list(sku.get("spec_detail_ids")):
            original = _text(value_id)
            match = unambiguous.get(original)
            if not match or match[0] in mappings:
                unmapped.append(original)
            else:
                mappings[match[0]] = match[1]
        draft_skus.append({
            "id": f"source-sku-{index}", "sourceSkuId": _text(sku.get("sku_id")) or None,
            "sourceLabel": _text(sku.get("sku_name")), "specValueIds": mappings,
            "sourceStatusRaw": json.dumps(sku["sku_status"], ensure_ascii=False)[:128]
                               if "sku_status" in sku and isinstance(sku["sku_status"], (str, int, float, bool)) else None,
            "unmappedSpecIds": unmapped, "price": _price(sku.get("price")),
            "stock": _stock(_dict(sku.get("stock_info")).get("stock_num")),
            # 来源的状态枚举尚未用真实样本验证，不能猜测 0/1 是在售还是下架。
            "state": "unknown",
        })
    if not raw_skus:
        # 采集表没有稳定的规格值映射时，只保留原 SKU，不按行号推测规格或图片。
        for index, sku in enumerate(skus):
            draft_skus.append({"id": f"source-sku-{index}", "sourceSkuId": _text(sku.get("sku_id")) or None,
                               "sourceLabel": _text(sku.get("sku_name")), "price": _price(sku.get("current_price"))})

    attributes = []
    for property_id, raw_values in _dict(_dict(payload.get("category_properties_value")).get("value")).items():
        values = [_dict(value) for value in _list(raw_values)]
        attributes.append({"id": _text(property_id), "name": _text(values[0].get("k")) if values else "",
                           "values": [{"id": _text(value.get("value_id")), "name": _text(value.get("value_name"))}
                                      for value in values]})

    first_has_images = dimensions and any(item["imageUrl"] for item in dimensions[0]["values"])
    return ProductDraft.model_validate({
        "title": _text(product.get("title")) or _text(goods.get("goodsName")),
        "categoryIds": [_text(goods.get(f"catId{i}")) for i in range(1, 5)
                        if is_douyin and _text(goods.get(f"catId{i}")) not in ("", "0")],
        "categoryPath": _text(product.get("category_path")) if is_douyin else "",
        "mainImages": image_items("main"), "detailImages": image_items("detail"),
        "attributes": attributes if is_douyin else [], "dimensions": dimensions,
        "imageDimensionId": dimensions[0]["id"] if first_has_images else None,
        "skus": draft_skus,
    })
