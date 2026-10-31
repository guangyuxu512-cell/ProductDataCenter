"""将采集数据读取为可编辑草稿，不改写采集数据或猜测缺失的 SKU 状态。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
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


def _douyin_spec_mapping(raw_ids: list, dimensions: list[dict], mapped_values: list[tuple[str, str, str]]):
    """Match stable IDs, including the composite value IDs accepted by RPA.

    A composite mapping is accepted only when every axis has one possible
    match and the full source-ID multiset is consumed exactly once.
    """
    tokens = [_text(value) for value in raw_ids]
    counts = Counter(item[0] for item in mapped_values)
    direct_ids = {original: (dimension, value) for original, dimension, value in mapped_values
                  if counts[original] == 1}
    direct, unmatched = {}, []
    for token in tokens:
        match = direct_ids.get(token)
        if not match or match[0] in direct:
            unmatched.append(token)
        else:
            direct[match[0]] = match[1]
    if not unmatched and len(direct) == len(dimensions):
        return direct, []

    remaining = Counter(tokens)
    if tokens and "" not in remaining:
        resolved, used = {}, Counter()
        for axis in dimensions:
            candidates = []
            for value in axis["values"]:
                original = value["sourceValueId"] or ""
                if not original:
                    continue
                parts = [original] if original in remaining else original.split("_")
                if (len(parts) < 2 and original not in remaining) or any(not part for part in parts):
                    continue
                claim = Counter(parts)
                if all(remaining[token] >= count for token, count in claim.items()):
                    candidates.append((value["id"], claim))
            if len(candidates) != 1:
                break
            resolved[axis["id"]] = candidates[0][0]
            used.update(candidates[0][1])
        if len(resolved) == len(dimensions) and used == remaining:
            return resolved, []
    return direct, unmatched


def _pdd_specs(raw_skus: list):
    """Preserve PDD's explicit SKU/spec data without mapping source categories.

    Source spec IDs are preferred. A missing ID can reuse a name only when the
    source contains at most one explicit ID for that name in the same axis.
    Conflicts remain unmatched for the operator to resolve.
    """
    key_ids_by_name, key_names_by_id = defaultdict(set), defaultdict(set)
    for sku in raw_skus:
        for raw in _list(_dict(sku).get("specs")):
            spec = _dict(raw)
            key, key_id = _text(spec.get("key")), _text(spec.get("keyId"))
            if key and key_id:
                key_ids_by_name[key].add(key_id)
                key_names_by_id[key_id].add(key)

    def axis_identity(spec):
        key, key_id = _text(spec.get("key")), _text(spec.get("keyId"))
        if not key or key_id and len(key_names_by_id[key_id]) > 1:
            return None
        if key_id:
            return ("id", key_id)
        known = key_ids_by_name[key]
        if len(known) > 1:
            return None
        return ("id", next(iter(known))) if known else ("name", key)

    value_ids_by_name, value_names_by_id = defaultdict(set), defaultdict(set)
    for sku in raw_skus:
        for raw in _list(_dict(sku).get("specs")):
            spec = _dict(raw)
            axis = axis_identity(spec)
            name, source_id = _text(spec.get("value")), _text(spec.get("valueId"))
            if axis and name and source_id:
                value_ids_by_name[(axis, name)].add(source_id)
                value_names_by_id[(axis, source_id)].add(name)

    def value_identity(axis, spec):
        name, source_id = _text(spec.get("value")), _text(spec.get("valueId"))
        if not name or source_id and len(value_names_by_id[(axis, source_id)]) > 1:
            return None
        if source_id:
            return ("id", source_id)
        known = value_ids_by_name[(axis, name)]
        if len(known) > 1:
            return None
        return ("id", next(iter(known))) if known else ("name", name)

    axes, axes_by_key, values_by_key = [], {}, {}
    for sku in raw_skus:
        for raw in _list(_dict(sku).get("specs")):
            spec = _dict(raw)
            key = axis_identity(spec)
            if key is None:
                continue
            if key not in axes_by_key:
                axis = {"id": f"pdd-dimension-{len(axes)}", "name": _text(spec.get("key")), "values": []}
                axes_by_key[key] = axis
                axes.append(axis)
            axis = axes_by_key[key]
            value_key = value_identity(key, spec)
            if value_key is None or (key, value_key) in values_by_key:
                continue
            value = {"id": f"{axis['id']}-value-{len(axis['values'])}",
                     "sourceValueId": value_key[1] if value_key[0] == "id" else None,
                     "name": _text(spec.get("value")), "imageUrl": ""}
            axis["values"].append(value)
            values_by_key[(key, value_key)] = value

    rows = []
    for index, raw_sku in enumerate(raw_skus):
        sku = _dict(raw_sku)
        mappings, unmatched, duplicate_axes = {}, [], set()
        specs = _list(sku.get("specs"))
        for raw in specs:
            spec = _dict(raw)
            axis_key = axis_identity(spec)
            value_key = value_identity(axis_key, spec) if axis_key else None
            axis = axes_by_key.get(axis_key)
            value = values_by_key.get((axis_key, value_key)) if axis_key and value_key else None
            marker = ":".join(filter(None, [_text(spec.get("key")), _text(spec.get("value"))])) or "未知规格"
            if not axis or not value:
                unmatched.append(marker)
            elif axis["id"] in mappings or axis["id"] in duplicate_axes:
                mappings.pop(axis["id"], None)
                duplicate_axes.add(axis["id"])
                unmatched.append(marker)
            else:
                mappings[axis["id"]] = value["id"]
        if not specs:
            unmatched.append("来源未提供规格")
        sale = sku.get("onSale")
        # The converter defaults a missing quantity to zero, indistinguishable
        # from a real zero. Keep it for reference but require confirmation.
        stock = _stock(sku.get("stock"))
        # An explicit null price is also converted to zero by the collector.
        price = _price(sku.get("groupPrice"))
        price_unconfirmed = price is not None and Decimal(price) == 0
        rows.append({"id": f"source-sku-{index}", "sourceSkuId": _text(sku.get("skuId")) or None,
                     "sourceLabel": _text(sku.get("name")),
                     "sourceStatusRaw": json.dumps(sale) if type(sale) is bool else None,
                     "sourceImageUrl": _text(sku.get("imageUrl")) or None,
                     "sourcePriceRaw": _text(sku.get("groupPrice")) or None,
                     "sourcePriceUnconfirmed": price_unconfirmed,
                     "sourceStockRaw": _text(sku.get("stock")) or None,
                     "sourceStockUnconfirmed": stock == 0,
                     "specValueIds": mappings, "unmappedSpecIds": unmatched,
                     "price": None if price_unconfirmed else price, "stock": None if stock == 0 else stock,
                     # The PDD converter defaults a missing source status to false;
                     # a false here alone does not prove that the SKU was off sale.
                     "state": "active" if sale is True else "unknown"})

    # A single source axis is the only case where per-SKU images can be tied to
    # values without guessing which dimension an image represents.
    if len(axes) == 1:
        axis = axes[0]
        for value in axis["values"]:
            urls = {row["sourceImageUrl"] for row in rows if not row["unmappedSpecIds"]
                    and row["specValueIds"].get(axis["id"]) == value["id"] and row["sourceImageUrl"]}
            if len(urls) == 1:
                value["imageUrl"] = next(iter(urls))
    return axes, rows


def draft_from_source(product: dict, skus: list[dict], images: list[dict], payload) -> ProductDraft:
    payload = _dict(payload)
    goods = _dict(payload.get("goodsInfo"))
    is_douyin = product.get("source_platform") == "douyin"
    is_pdd = product.get("source_platform") == "pinduoduo" and payload.get("schemaVersion") == "pdd-package-v1"
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
        if not result and is_pdd:
            for position, image in enumerate(_list(_dict(payload.get("images")).get(kind))):
                url = _image(image)
                if url:
                    result.append({"id": f"source-{kind}-{position}", "url": url})
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

    raw_skus = _list(_dict(_dict(payload.get("goodsSkuInfo")).get("spec_detail")).get("value"))
    draft_skus = []
    for index, raw_sku in enumerate(raw_skus):
        sku = _dict(raw_sku)
        mappings, unmapped = _douyin_spec_mapping(_list(sku.get("spec_detail_ids")), dimensions, mapped_values)
        status = sku.get("sku_status")
        raw_ids = [_text(value) for value in _list(sku.get("spec_detail_ids"))]
        original_sku = _dict(_dict(goods.get("skuInfoMap")).get("_".join(raw_ids)))
        original_status = original_sku.get("sku_status")
        stock = _stock(_dict(sku.get("stock_info")).get("stock_num"))
        stock_placeholder = is_douyin and "skuInfoMap" in goods and stock == 999
        # The collector's normalized false also covers a missing raw status.
        # Only an explicit raw "1" confirms the false/off branch.
        known_off = status is False and type(original_status) in (str, int) and str(original_status) == "1"
        draft_skus.append({
            "id": f"source-sku-{index}", "sourceSkuId": _text(sku.get("sku_id")) or None,
            "sourceLabel": _text(sku.get("sku_name")), "specValueIds": mappings,
            "sourceStatusRaw": json.dumps(sku["sku_status"], ensure_ascii=False)[:128]
                               if "sku_status" in sku and isinstance(sku["sku_status"], (str, int, float, bool)) else None,
            "sourceStockRaw": str(stock) if stock is not None else None,
            "sourceStockPlaceholder": stock_placeholder,
            "unmappedSpecIds": unmapped, "price": _price(sku.get("price")),
            "stock": None if stock_placeholder else stock,
            "state": ("active" if status is True else "inactive" if known_off else "unknown")
                     if is_douyin else "unknown",
        })
    if is_pdd and _list(payload.get("skus")):
        dimensions, draft_skus = _pdd_specs(_list(payload.get("skus")))
        raw_skus = _list(payload.get("skus"))
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

    source_attributes = []
    if is_pdd:
        for index, item in enumerate(_list(_dict(payload.get("product")).get("properties"))):
            property_data = _dict(item)
            source_attributes.append({"id": _text(property_data.get("propertyId")) or f"pdd-source-property-{index}",
                                      "name": _text(property_data.get("key")),
                                      "values": [{"id": "", "name": _text(value)}
                                                 for value in _list(property_data.get("values"))]})
    first_has_images = dimensions and any(item["imageUrl"] for item in dimensions[0]["values"])
    return ProductDraft.model_validate({
        "title": _text(product.get("title")) or _text(goods.get("goodsName")),
        "sourceCategoryIds": [_text(value) for value in _list(_dict(payload.get("product")).get("categoryIds"))
                              if is_pdd and _text(value) not in ("", "0")],
        "sourceAttributes": source_attributes,
        "categoryIds": [_text(goods.get(f"catId{i}")) for i in range(1, 5)
                        if is_douyin and _text(goods.get(f"catId{i}")) not in ("", "0")],
        "categoryPath": _text(product.get("category_path")) if is_douyin else "",
        "mainImages": image_items("main"), "detailImages": image_items("detail"),
        "attributes": attributes if is_douyin else [], "dimensions": dimensions,
        "imageDimensionId": dimensions[0]["id"] if first_has_images else None,
        "skus": draft_skus,
    })
