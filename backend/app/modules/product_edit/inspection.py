"""Local draft checks and an unpublished candidate for the current RPA contract.

Platform category schemas, store eligibility and final publication remain
separate checks. This module never changes a product or returns a package to RPA.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from .models import DraftInspection, InspectionIssue, ProductDraft, validate_title


def _https(value: str) -> bool:
    try:
        if re.search(r"\s", value):
            return False
        url = urlsplit(value)
        return bool(url.scheme.lower() == "https" and url.hostname and not url.username and not url.password
                    and (url.port is None or 1 <= url.port <= 65535))
    except ValueError:
        return False


def _axis_name(value: str) -> str:
    # The current RPA strips a trailing numeric counter from an axis name.
    return re.sub(r"[（(]\d+[）)]$", "", value.strip()).strip()


def inspect_draft(draft: ProductDraft, *, product_id: str, source_platform: str,
                  source_product_id: str | None, source_changed: bool = False) -> DraftInspection:
    issues: list[InspectionIssue] = []

    def add(code: str, tab: str, message: str, kind: str = "local"):
        issues.append(InspectionIssue(code=code, tab=tab, message=message, kind=kind))

    try:
        validate_title(draft.title)
    except ValueError as error:
        add("TITLE_INVALID", "base", str(error))
    if not draft.categoryIds or any(not value.strip() or value.strip() == "0" for value in draft.categoryIds):
        add("TARGET_CATEGORY_REQUIRED", "base", "请选择抖店类目")
    if source_changed:
        add("SOURCE_CHANGED", "base", "来源数据已更新，请先核对草稿")

    if not draft.mainImages:
        add("MAIN_IMAGE_REQUIRED", "images", "请添加主图")
    for label, items in (("主图", draft.mainImages), ("详情图", draft.detailImages)):
        seen: set[str] = set()
        for index, item in enumerate(items, 1):
            if not _https(item.url):
                add("IMAGE_UNAVAILABLE_TO_RPA", "images", f"{label} {index} 需要可供 RPA 读取的 HTTPS 地址", "rpa")
            if item.url and item.url in seen:
                add("DUPLICATE_IMAGE", "images", f"{label} {index} 与其他图片链接重复", "rpa")
            seen.add(item.url)

    axes = draft.dimensions
    if not axes:
        add("SPEC_REQUIRED", "sku", "请添加规格类型和规格值")
    if len(axes) > 3:
        add("TOO_MANY_AXES", "sku", "当前最多支持 3 组规格")
    axis_names: set[str] = set()
    for index, axis in enumerate(axes, 1):
        name = _axis_name(axis.name)
        if not name or name in axis_names:
            add("SPEC_NAME_INVALID", "sku", f"第 {index} 组规格名称为空或重复")
        axis_names.add(name)
        if not axis.values:
            add("SPEC_VALUES_REQUIRED", "sku", f"第 {index} 组规格没有规格值")
        names: set[str] = set()
        for value in axis.values:
            name = value.name.strip()
            if not name or name in names:
                add("SPEC_VALUE_INVALID", "sku", f"第 {index} 组规格值为空或重复")
            names.add(name)
    if draft.imageDimensionId and axes:
        images = [value.imageUrl.strip() for value in axes[0].values]
        if any(images) and not all(images):
            add("SPEC_IMAGES_INCOMPLETE", "sku", "规格图需全部填写或全部清空")
        if any(value and not _https(value) for value in images):
            add("SPEC_IMAGE_UNAVAILABLE_TO_RPA", "sku", "规格图需要可供 RPA 读取的 HTTPS 地址", "rpa")

    if not draft.skus:
        add("SKU_REQUIRED", "sku", "请添加 SKU")
    combinations: set[tuple[str, ...]] = set()
    for index, sku in enumerate(draft.skus, 1):
        valid = not sku.unmappedSpecIds and len(sku.specValueIds) == len(axes) and bool(axes)
        for axis in axes:
            valid = valid and any(value.id == sku.specValueIds.get(axis.id) for value in axis.values)
        if not valid:
            add("SKU_SPEC_UNRESOLVED", "sku", f"第 {index} 个 SKU 的规格尚未确认")
        else:
            combination = tuple(sku.specValueIds[axis.id] for axis in axes)
            if combination in combinations:
                add("SKU_COMBINATION_DUPLICATE", "sku", f"第 {index} 个 SKU 的规格组合重复")
            combinations.add(combination)
        if sku.price is None:
            add("SKU_PRICE_REQUIRED", "sku", f"第 {index} 个 SKU 缺少价格")
        if sku.stock is None:
            add("SKU_STOCK_REQUIRED", "sku", f"第 {index} 个 SKU 缺少库存")
        if sku.state == "unknown":
            add("SKU_STATE_UNCONFIRMED", "sku", f"第 {index} 个 SKU 的在售状态尚未确认")
        if sku.merchantCode.strip():
            add("RPA_MERCHANT_CODE_UNSUPPORTED", "sku", f"第 {index} 个 SKU 的商家编码尚未接入 RPA", "rpa")
    if axes and all(axis.values for axis in axes):
        expected = math.prod(len(axis.values) for axis in axes)
        if expected > 1000:
            add("SKU_COMBINATIONS_TOO_MANY", "sku", "当前最多支持编辑 1000 个规格组合")
        elif len(combinations) < expected:
            add("SKU_COMBINATIONS_UNCONFIRMED", "sku", f"还有 {expected - len(combinations)} 个规格组合未确认")

    for attribute in draft.attributes:
        if attribute.values and (not attribute.name.strip() or any(not value.name.strip() for value in attribute.values)):
            add("ATTRIBUTE_VALUE_INVALID", "attributes", "商品属性名称或属性值为空")

    if source_platform not in {"douyin", "pinduoduo"}:
        add("RPA_SOURCE_UNSUPPORTED", "base", "RPA 尚未接入该商品来源", "rpa")
    if source_platform in {"douyin", "pinduoduo"} and not re.fullmatch(r"\d{8,}", source_product_id or "", re.ASCII):
        add("SOURCE_ID_INVALID", "base", "来源商品 ID 无效", "rpa")

    candidate_hash = None
    if not issues:
        candidate = build_candidate(draft, source_product_id or product_id)
        candidate_hash = hashlib.sha256(candidate).hexdigest()
    return DraftInspection(localStatus="issues" if any(item.kind == "local" for item in issues) else "passed",
                           rpaStatus="blocked" if issues else "compatible",
                           platformStatus="not_checked", canPublish=False, candidateSha256=candidate_hash,
                           issues=issues)


def build_candidate(draft: ProductDraft, source_id: str) -> bytes:
    """Build an internal candidate matching the pinned RPA reader, not a published package.

    The caller must first check local and RPA issues. Source records are never
    edited, and unknown source-only fields are deliberately not projected.
    """
    axes = draft.dimensions
    main_images = [item.url.strip() for item in draft.mainImages]
    detail_images = [item.url.strip() for item in draft.detailImages]
    spec_values = [{"name": _axis_name(axis.name), "spec_values": [
        {"id": value.id, "name": value.name.strip(),
         "img_url": value.imageUrl.strip() if draft.imageDimensionId == axis.id else ""}
        for value in axis.values]} for axis in axes]
    sku_rows = [{"spec_detail_ids": [sku.specValueIds[axis.id] for axis in axes],
                 "price": sku.price, "stock_info": {"stock_num": sku.stock}, "sku_status": sku.state == "active"}
                for sku in draft.skus]
    attributes = {attribute.id: [{"k": attribute.name.strip(), "value_id": value.id,
                                  "value_name": value.name.strip()} for value in attribute.values]
                  for attribute in draft.attributes if attribute.values}
    goods = {"goodsId": source_id, "goodsName": draft.title, "goodsImageList": main_images}
    for index in range(4):
        goods[f"catId{index + 1}"] = draft.categoryIds[index] if index < len(draft.categoryIds) else "0"
    payload = {"goodsId": source_id, "goodsInfo": goods,
               "goodsSkuInfo": {"spec_detail": {"value": sku_rows}},
               "spec_detail_value": {"value": spec_values},
               "goodsDetailInfo": {"detail_imgs": detail_images},
               "category_properties_value": {"value": attributes}}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
