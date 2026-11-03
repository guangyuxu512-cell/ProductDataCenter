"""Durable, read-only checks for newly saved product packages."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from threading import Lock

from fastapi import Response

from app.modules.category_lookup.api import AutoSchemaBody, PredictBody, predict, schema_auto
from app.modules.category_lookup.client import DouyinCategoryClient
from app.modules.central.client import CentralApplicationClient
from app.modules.products.service import ProductService

_schema_locks = [Lock() for _ in range(64)]


def _missing_required(fields: list, source: list, target: list, platform: str) -> list[str]:
    names = Counter(str(field.label).strip() for field in fields)
    missing = []
    for field in fields:
        if not field.required:
            continue
        value = None
        if platform == "pinduoduo":
            saved = [item for item in target if item["id"] == field.id]
            if saved:
                value = saved[0]["values"]
        elif platform == "douyin":
            exact = [item for item in source if item["id"] and item["id"] == field.id]
            if len(exact) == 1:
                value = exact[0]["values"]
            elif len(exact) > 1:
                value = []
        if value is None:
            same_name = [item for item in source if item["name"].strip() == field.label.strip()]
            if names[field.label.strip()] == 1 and len(same_name) == 1:
                value = same_name[0]["values"]
                if platform == "pinduoduo" and field.options:
                    counts = Counter(option.label for option in field.options)
                    if any(counts[str(v).strip()] != 1 for v in value):
                        value = []
        if not value or not any(str(v).strip() for v in value):
            missing.append(field.label)
    return missing


def check_product(product_id: str, service: ProductService, central: CentralApplicationClient,
                  lookup: DouyinCategoryClient) -> dict:
    detail = service.repository.detail(product_id)
    if not detail:
        raise ValueError("商品不存在")
    row = detail["product"]
    platform, title = row["source_platform"], row["title"] or ""
    issues = []
    if not title.strip():
        issues.append("商品标题")
    if not row.get("main_image_url") and not any(item.get("image_type") == "main" and
            (item.get("source_url") or item.get("rel_path")) for item in detail["images"]):
        issues.append("商品主图")
    skus = detail["skus"]
    if not skus:
        issues.append("SKU 规格")
    else:
        try:
            if any(sku["current_price"] is None or Decimal(str(sku["current_price"])) <= 0 for sku in skus):
                issues.append("SKU 价格")
        except (InvalidOperation, TypeError):
            issues.append("SKU 价格")
    result = {"productId": product_id, "title": title, "status": "ready", "issues": issues}
    if platform == "pinduoduo" and not detail["targetCategory"]:
        prediction = predict(PredictBody(productId=product_id), Response(), central, lookup, service)
        result["prediction"] = prediction.model_dump(mode="json")
        for item in prediction.missing:
            if item not in issues:
                issues.append(item)
        if not prediction.missing:
            issues.append("待确认抖店类目" if prediction.candidates else "未找到推荐类目，请手动选择")
        result["status"] = "needs_completion" if prediction.missing else "needs_category"
        return result
    category_id = (detail["sourceCategoryId"] if platform == "douyin" else
                   detail["targetCategory"][-1]["id"] if platform == "pinduoduo" and detail["targetCategory"] else None)
    if not category_id:
        issues.append("抖店类目")
        result["status"] = "needs_category"
        return result
    # Coalesce simultaneous first requests for the same category; subsequent
    # checks use the existing category cache until the user refreshes it.
    with _schema_locks[hash(category_id) % len(_schema_locks)]:
        schema = schema_auto(AutoSchemaBody(categoryId=category_id, title=title), Response(), central, lookup)
    missing = _missing_required(schema.attributes, detail["sourceAttributes"], detail["targetAttributes"], platform)
    if missing:
        issues.append("必填属性：" + "、".join(missing))
    result["status"] = "needs_completion" if issues else "ready"
    return result
