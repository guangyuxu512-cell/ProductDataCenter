"""Conservative preparation of a verified legacy Jushuitan category repair."""
from copy import deepcopy

from app.modules.category_lookup.resolver import category_ids
from .source_attributes import source_attributes


def prepare_legacy_category_repair(package: dict, source: list[dict], target: list[dict]) -> dict:
    """Add provenance only; callers must independently verify both category paths."""
    if (not isinstance(package, dict) or "douyinTarget" in package
            or "_productDataCenterJushuitanSource" in package):
        raise ValueError("已有类目来源或目标信息，拒绝覆盖")
    if not source or not target or len(source) > 4 or len(target) > 4:
        raise ValueError("来源或目标类目不完整")
    for parts in (source, target):
        for item in parts:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not item["id"].isascii() or not item["id"].isdigit()
                    or not item["id"].strip("0") or len(item["id"]) > 20
                    or not isinstance(item.get("name"), str) or not item["name"].strip()):
                raise ValueError("类目 ID 或名称无效")
    if category_ids(package.get("goodsInfo")) != [item["id"] for item in target]:
        raise ValueError("已保存的类目已变化")
    block = package.get("category_properties_value")
    values = block.get("value") if isinstance(block, dict) else None
    detail = package.get("goodsDetailInfo")
    formats = detail.get("product_format") if isinstance(detail, dict) else None
    attributes = source_attributes(values, formats)
    ids = [item["id"] for item in attributes]
    if any(not identity for identity in ids) or len(ids) != len(set(ids)):
        raise ValueError("现有属性无法唯一对应")
    populated = {str(key) for key, rows in (values or {}).items() if isinstance(rows, list) and rows} if isinstance(values, dict) else set()
    if not populated.issubset(set(ids)):
        raise ValueError("现有属性无法完整读取")
    result = deepcopy(package)
    result["_productDataCenterJushuitanSource"] = {"category": deepcopy(source)}
    result["douyinTarget"] = {"category": deepcopy(target), "attributes": {
        item["id"]: {"name": item["name"], "values": deepcopy(item["valueItems"])} for item in attributes
    }}
    return result
