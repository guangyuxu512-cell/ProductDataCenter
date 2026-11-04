"""Durable, read-only checks for newly saved product packages."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from threading import Lock

from fastapi import Response

from app.modules.category_lookup.api import (
    AutoSchemaBody, PredictBody, PredictManualBody, predict, predict_manual, schema_auto,
)
from app.modules.category_lookup.client import DouyinCategoryClient
from app.modules.central.client import CentralApplicationClient
from app.modules.products.service import ProductService

_schema_locks = [Lock() for _ in range(64)]


def _field_values(field, fields: list, source: list, target: list, platform: str):
    names = Counter(str(field.label).strip() for field in fields)
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
    return [] if value is None else [str(item).strip() for item in value if str(item).strip()]


def _attribute_problem(field, values: list[str]) -> str | None:
    if not values:
        return "未填写" if field.required else None
    control = getattr(field, "control", "text")
    if control == "single" and len(values) != 1:
        return "只能选择一项"
    if control == "number":
        try:
            if any(not Decimal(value).is_finite() for value in values):
                return "数字无效"
        except (InvalidOperation, ValueError):
            return "数字无效"
    if field.options and not getattr(field, "allowCustom", False):
        labels = Counter(option.label.strip() for option in field.options)
        if any(labels[value] != 1 for value in values):
            return "包含无效选项"
    return None


def _attribute_problems(fields: list, source: list, target: list, platform: str) -> list[tuple[object, str]]:
    return [(field, problem) for field in fields
            if (problem := _attribute_problem(field, _field_values(field, fields, source, target, platform)))]


def _missing_required(fields: list, source: list, target: list, platform: str) -> list[str]:
    """Compatibility helper used by focused tests and older callers."""
    return [field.label for field, problem in _attribute_problems(fields, source, target, platform)
            if problem == "未填写"]


def _add_issue(result: dict, code: str, message: str, tab: str, **location) -> None:
    result["issues"].append(message)
    result["issueDetails"].append({"code": code, "message": message, "tab": tab, **location})


def _main_image(detail: dict) -> str:
    value = detail["product"].get("main_image_url")
    if value:
        return str(value)
    return next((str(item.get("source_url") or "") for item in detail["images"]
                 if item.get("image_type") == "main" and item.get("source_url")), "")


def check_product(product_id: str, service: ProductService, central: CentralApplicationClient,
                  lookup: DouyinCategoryClient) -> dict:
    detail = service.repository.detail(product_id)
    if not detail:
        raise ValueError("商品不存在")
    row = detail["product"]
    platform, title = row["source_platform"], row["title"] or ""
    result = {"productId": product_id, "title": title, "status": "ready",
              "issues": [], "issueDetails": []}
    if not title.strip():
        _add_issue(result, "title_missing", "商品标题未填写", "base", fieldId="title")
    image_url = _main_image(detail)
    if not image_url and not any(item.get("image_type") == "main" and item.get("rel_path")
                                 for item in detail["images"]):
        _add_issue(result, "main_image_missing", "商品主图未填写", "images", fieldId="mainImages")
    skus = detail["skus"]
    if not skus:
        _add_issue(result, "sku_missing", "SKU 规格未填写", "sku", fieldId="skus")
    else:
        for index, sku in enumerate(skus):
            try:
                price = Decimal(str(sku["current_price"]))
                invalid = not price.is_finite() or price <= 0
            except (InvalidOperation, TypeError, ValueError):
                invalid = True
            if invalid:
                _add_issue(result, "sku_price_invalid", f"第 {index + 1} 个 SKU 价格无效", "sku",
                           fieldId="price", skuIndex=index, skuId=str(sku.get("sku_id") or ""))
    needs_prediction = not detail["targetCategory"] and (
        platform == "pinduoduo" or (platform == "douyin" and product_id.startswith("manual:"))
    )
    if needs_prediction and not detail["sourceCategoryId"]:
        prediction = (predict(PredictBody(productId=product_id), Response(), central, lookup, service)
                      if platform == "pinduoduo" else
                      predict_manual(PredictManualBody(title=title, imageUrl=image_url), Response(), central, lookup))
        result["prediction"] = prediction.model_dump(mode="json")
        if not prediction.missing:
            message = "待选择类目" if prediction.candidates else "未找到推荐类目，请手动选择"
            _add_issue(result, "category_confirmation_required", message, "base", fieldId="category")
        non_category = [item for item in result["issueDetails"]
                        if item["code"] != "category_confirmation_required"]
        result["status"] = "needs_completion" if prediction.missing or non_category else "needs_category"
        return result
    category_id = (detail["sourceCategoryId"] if platform == "douyin" else
                   detail["targetCategory"][-1]["id"] if platform == "pinduoduo" and detail["targetCategory"] else None)
    if not category_id:
        _add_issue(result, "category_missing", "类目未选择", "base", fieldId="category")
        result["status"] = "needs_category"
        return result
    # Coalesce simultaneous first requests for the same category; subsequent
    # checks use the existing category cache until the user refreshes it.
    with _schema_locks[hash(category_id) % len(_schema_locks)]:
        schema = schema_auto(AutoSchemaBody(categoryId=category_id, title=title), Response(), central, lookup)
    problems = _attribute_problems(schema.attributes, detail["sourceAttributes"],
                                   detail["targetAttributes"], platform)
    for field, problem in problems:
        _add_issue(result, "attribute_invalid" if problem != "未填写" else "attribute_missing",
                   f"{field.label}{problem}", "attributes", fieldId=field.id)
    result["status"] = "needs_completion" if result["issues"] else "ready"
    return result
