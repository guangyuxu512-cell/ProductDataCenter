"""Make narrowly scoped changes to a database package without discarding source fields."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re
from uuid import uuid4

from .errors import ProductRequestError
from .schemas import ProductEdit, SkuEdit


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


def move_spec_image_group(data: dict, target: int) -> None:
    """Move a validated group to the front without inventing SKU combinations."""
    value_groups = _mapping(data.get("spec_detail_value"), "商品缺少销售规格").get("value")
    info = _mapping(data.get("goodsSkuInfo"), "商品缺少销售规格")
    sku_groups = info.get("sku_detail")
    detail = _mapping(info.get("spec_detail"), "商品缺少 SKU 组合")
    rows = detail.get("value")
    goods = _mapping(data.get("goodsInfo"), "商品缺少 SKU 来源映射")
    source_map = _mapping(goods.get("skuInfoMap"), "商品缺少 SKU 来源映射")
    if not isinstance(value_groups, list) or not isinstance(sku_groups, list) or not isinstance(rows, list):
        raise ProductRequestError("规格数据格式无效，无法调整规格顺序")
    count = len(value_groups)
    if not 1 <= target < count <= 3 or len(sku_groups) != count:
        raise ProductRequestError("规格数据不完整，无法调整规格顺序")
    groups = []
    for value_group, sku_group in zip(value_groups, sku_groups, strict=True):
        values = _mapping(value_group, "规格数据无效").get("spec_values")
        items = _mapping(sku_group, "规格数据无效").get("spec_item_list")
        if not isinstance(values, list) or not isinstance(items, list):
            raise ProductRequestError("规格数据不完整，无法调整规格顺序")
        value_ids = [str(item["id"]) if item.get("id") is not None else "" for item in values if isinstance(item, dict)]
        item_ids = [str(item["spec_item_id"]) if item.get("spec_item_id") is not None else "" for item in items if isinstance(item, dict)]
        if (not value_ids or len(value_ids) != len(values) or len(item_ids) != len(items) or
                len(set(value_ids)) != len(value_ids) or len(set(item_ids)) != len(item_ids) or
                set(value_ids) != set(item_ids) or any(not value or "_" in value for value in value_ids)):
            raise ProductRequestError("规格值无法唯一对应，无法调整规格顺序")
        groups.append(set(value_ids))
    if len(set.union(*groups)) != sum(map(len, groups)):
        raise ProductRequestError("规格值标识重复，无法调整规格顺序")

    def reorder_ids(ids):
        if len(ids) != count or any(str(value) not in groups[index] for index, value in enumerate(ids)):
            raise ProductRequestError("SKU 组合与规格顺序不一致，无法调整")
        return [ids[index] for index in order]

    order = [target, *[index for index in range(count) if index != target]]
    row_keys = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("spec_detail_ids"), list):
            raise ProductRequestError("SKU 组合格式无效，无法调整")
        reorder_ids(row["spec_detail_ids"])
        row_keys.append("_".join(str(value) for value in row["spec_detail_ids"]))
    if len(set(row_keys)) != len(row_keys) or any(key not in source_map for key in row_keys):
        raise ProductRequestError("SKU 来源映射不完整，无法调整规格顺序")
    for key in source_map:
        reorder_ids(str(key).split("_"))
    prices = data.get("_source_sku_prices")
    if prices is not None:
        if not isinstance(prices, dict):
            raise ProductRequestError("SKU 来源数据格式无效，无法调整")
        for key in prices:
            reorder_ids(str(key).split("_"))

    indexed = [group.get("spec_index") for group in sku_groups]
    if any(value is not None for value in indexed):
        try:
            numbers = [int(value) for value in indexed]
        except (TypeError, ValueError):
            raise ProductRequestError("规格顺序标识无效，无法调整") from None
        if numbers not in (list(range(count)), list(range(1, count + 1))):
            raise ProductRequestError("规格顺序标识不连续，无法调整")
        start = numbers[0]
    else:
        start = None

    # A picture belongs to one dimension and cannot be transferred to another.
    for group_index in range(count):
        if group_index == target:
            continue
        for value in value_groups[group_index]["spec_values"]:
            value["img_url"] = ""
        for item in sku_groups[group_index]["spec_item_list"]:
            item["big_pic"] = ""
            if "small_pic" in item:
                item["small_pic"] = ""
    value_groups[:] = [value_groups[index] for index in order]
    sku_groups[:] = [sku_groups[index] for index in order]
    if start is not None:
        for index, group in enumerate(sku_groups):
            group["spec_index"] = str(index + start) if isinstance(group["spec_index"], str) else index + start
    for row in rows:
        row["spec_detail_ids"] = reorder_ids(row["spec_detail_ids"])
    goods["skuInfoMap"] = {"_".join(reorder_ids(str(key).split("_"))): value for key, value in source_map.items()}
    if prices is not None:
        data["_source_sku_prices"] = {"_".join(reorder_ids(str(key).split("_"))): value for key, value in prices.items()}


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


def _sku_key(source: dict, fallback: str) -> str:
    return str(source.get("sku_id") or source.get("skuId") or source.get("id") or
               source.get("_local_sku_key") or fallback)


def _edit_spec_structure(data: dict, structure) -> None:
    """Update the coupled source structures, retaining original rows and their metadata."""
    value_groups = _mapping(data.get("spec_detail_value"), "商品缺少销售规格").get("value")
    info = _mapping(data.get("goodsSkuInfo"), "商品缺少销售规格")
    sku_groups = info.get("sku_detail")
    rows = _mapping(info.get("spec_detail"), "商品缺少 SKU 组合").get("value")
    goods = _mapping(data.get("goodsInfo"), "商品缺少 SKU 来源映射")
    source_map = _mapping(goods.get("skuInfoMap"), "商品缺少 SKU 来源映射")
    if not isinstance(value_groups, list) or not isinstance(sku_groups, list) or not isinstance(rows, list) or len(value_groups) != len(sku_groups):
        raise ProductRequestError("规格数据不完整，无法编辑")
    old_values = []
    old_items = []
    for value_group, sku_group in zip(value_groups, sku_groups, strict=True):
        values = _mapping(value_group, "规格数据无效").get("spec_values")
        items = _mapping(sku_group, "规格数据无效").get("spec_item_list")
        if not isinstance(values, list) or not isinstance(items, list):
            raise ProductRequestError("规格数据不完整，无法编辑")
        vm = {str(v.get("id")): v for v in values if isinstance(v, dict) and v.get("id") is not None}
        im = {str(v.get("spec_item_id")): v for v in items if isinstance(v, dict) and v.get("spec_item_id") is not None}
        if len(vm) != len(values) or len(im) != len(items) or set(vm) != set(im) or any(not key or "_" in key for key in vm):
            raise ProductRequestError("规格值无法唯一对应，无法编辑")
        old_values.append(vm)
        old_items.append(im)
    all_old_ids = [key for group in old_values for key in group]
    if len(all_old_ids) != len(set(all_old_ids)):
        raise ProductRequestError("规格值标识重复，无法编辑")
    old_rows = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("spec_detail_ids"), list):
            raise ProductRequestError("SKU 组合格式无效")
        ids = [str(value) for value in row["spec_detail_ids"]]
        if len(ids) != len(old_values) or any(value not in old_values[i] for i, value in enumerate(ids)):
            raise ProductRequestError("SKU 组合与规格不一致")
        key = "_".join(ids)
        if key in old_rows or not isinstance(source_map.get(key), dict):
            raise ProductRequestError("SKU 来源映射不完整或重复")
        old_rows[key] = row

    groups = structure.groups
    source_indices = [group.sourceIndex for group in groups if group.sourceIndex is not None]
    if len(source_indices) != len(set(source_indices)) or any(index >= len(old_values) for index in source_indices):
        raise ProductRequestError("规格类型与原数据不能唯一对应")
    group_names = [re.sub(r"\s*[（(]\d+[）)]\s*$", "", group.name).strip() for group in groups]
    if any(not name for name in group_names) or len(set(group_names)) != len(group_names):
        raise ProductRequestError("规格类型名称不能为空或重复")
    all_ids = [value.id for group in groups for value in group.values]
    if len(all_ids) != len(set(all_ids)):
        raise ProductRequestError("规格值标识重复")
    new_value_groups = []
    new_sku_groups = []
    for index, group in enumerate(groups):
        if len({value.name for value in group.values}) != len(group.values):
            raise ProductRequestError("同一规格类型下的规格值不能重复")
        original = group.sourceIndex
        value_group = deepcopy(value_groups[original]) if original is not None else {}
        sku_group = deepcopy(sku_groups[original]) if original is not None else {}
        value_group["name"] = group.name
        sku_group["name"] = group.name
        if "spec_index" in sku_group:
            start = 1 if sku_groups and sku_groups[0].get("spec_index") in (1, "1") else 0
            sku_group["spec_index"] = str(index + start) if isinstance(sku_group["spec_index"], str) else index + start
        values, items = [], []
        for value in group.values:
            if value.id in all_old_ids and (original is None or value.id not in old_values[original]):
                raise ProductRequestError("规格值不能移动到其他规格类型")
            if value.id not in all_old_ids and not value.id.startswith("local-"):
                raise ProductRequestError("新增规格值标识无效")
            val = deepcopy(old_values[original].get(value.id, {})) if original is not None else {}
            item = deepcopy(old_items[original].get(value.id, {})) if original is not None else {}
            old_url = val.get("img_url") or item.get("big_pic") or item.get("small_pic") or ""
            is_new = value.id not in all_old_ids
            val.update(id=value.id, name=value.name)
            item.update(spec_item_id=value.id, name=value.name)
            if is_new or old_url != value.url:
                val["img_url"] = value.url
                item["big_pic"] = value.url
                if "small_pic" in item:
                    item["small_pic"] = value.url
            values.append(val)
            items.append(item)
        value_group["spec_values"] = values
        sku_group["spec_item_list"] = items
        new_value_groups.append(value_group)
        new_sku_groups.append(sku_group)

    new_rows, new_map, remapped, changes = [], {}, {}, []
    group_ids = [{value.id for value in group.values} for group in groups]
    for draft in structure.skus:
        ids = draft.specIds
        if len(ids) != len(groups) or any(value not in group_ids[i] for i, value in enumerate(ids)):
            raise ProductRequestError("SKU 组合与当前规格不一致")
        key = "_".join(ids)
        if key in new_map:
            raise ProductRequestError("SKU 组合重复，请先处理重复组合")
        old_key = "_".join(draft.sourceSpecIds) if draft.sourceSpecIds else None
        if old_key is not None:
            if old_key not in old_rows or old_key in remapped:
                raise ProductRequestError("SKU 来源无法唯一对应，请刷新后重试")
            old_ids = draft.sourceSpecIds
            if any(group.sourceIndex is not None and ids[i] != old_ids[group.sourceIndex] for i, group in enumerate(groups)):
                raise ProductRequestError("已有 SKU 不能指向其他规格值")
            row, source = deepcopy(old_rows[old_key]), deepcopy(source_map[old_key])
            if key != old_key and not any(source.get(field) for field in ("sku_id", "skuId", "id", "_local_sku_key")):
                source["_local_sku_key"] = old_key
            remapped[old_key] = key
        else:
            row = {"stock_info": {}}
            source = {"_local_sku_key": "local-" + uuid4().hex}
        old_price = str(row.get("price") or "")
        old_stock = row.get("stock_info", {}).get("stock_num") if isinstance(row.get("stock_info"), dict) else None
        old_stock = "" if old_stock is None else str(old_stock)
        old_enabled = row.get("sku_status") if isinstance(row.get("sku_status"), bool) else None
        row["spec_detail_ids"] = list(ids)
        new_rows.append(row)
        new_map[key] = source
        values = {"specIds": ids}
        if draft.price != old_price:
            try:
                price = Decimal(draft.price)
                if not price.is_finite() or price <= 0 or price > 9999999999 or price.as_tuple().exponent < -2:
                    raise InvalidOperation
            except InvalidOperation:
                raise ProductRequestError("SKU 价格必须大于 0，最多两位小数") from None
            values["price"] = price
        if draft.stock != old_stock:
            if not re.fullmatch(r"[0-9]+", draft.stock) or int(draft.stock) > 2147483647:
                raise ProductRequestError("SKU 库存必须是非负整数")
            values["stock"] = int(draft.stock)
        if draft.merchantCode != str(row.get("merchant_code") or ""):
            values["merchantCode"] = draft.merchantCode
        if draft.enabled is not None and draft.enabled != old_enabled:
            values["enabled"] = draft.enabled
        if old_key is None and ("price" not in values or "stock" not in values):
            raise ProductRequestError("新增 SKU 必须填写价格和库存")
        if len(values) > 1:
            changes.append(SkuEdit(**values))

    def map_hidden(key):
        old_ids = str(key).split("_")
        if len(old_ids) != len(old_values) or any(value not in old_values[i] for i, value in enumerate(old_ids)):
            raise ProductRequestError("SKU 来源映射不完整，无法安全编辑")
        result = [old_ids[g.sourceIndex] if g.sourceIndex is not None else g.values[0].id for g in groups]
        if any(value not in group_ids[i] for i, value in enumerate(result)):
            raise ProductRequestError("删除的规格值仍被其他来源记录使用，无法安全保存")
        return "_".join(result)

    for old_key, source in source_map.items():
        if old_key in old_rows:
            continue
        key = map_hidden(old_key)
        if key in new_map:
            raise ProductRequestError("规格调整导致来源 SKU 重复，无法安全保存")
        new_map[key] = deepcopy(source)
        remapped[old_key] = key
    if "_source_sku_prices" in data:
        prices = _mapping(data["_source_sku_prices"], "SKU 来源价格格式无效")
        new_prices = {}
        for old_key, price in prices.items():
            if old_key in old_rows and old_key not in remapped:
                continue
            key = remapped.get(old_key) or map_hidden(old_key)
            if key in new_prices:
                raise ProductRequestError("规格调整导致来源 SKU 价格重复")
            new_prices[key] = price
        data["_source_sku_prices"] = new_prices
    value_groups[:] = new_value_groups
    sku_groups[:] = new_sku_groups
    rows[:] = new_rows
    goods["skuInfoMap"] = new_map
    _edit_skus(data, changes)


def apply_edit(source: dict, platform: str, edit: ProductEdit) -> dict:
    """Return a modified copy; reject shapes we cannot faithfully translate."""
    data = deepcopy(_mapping(source, "商品数据包格式无效"))
    if platform == "douyin":
        goods = _mapping(data.get("goodsInfo"), "抖音商品数据包缺少商品信息")
        if edit.specStructure is not None:
            _edit_spec_structure(data, edit.specStructure)
        if edit.skus is not None:
            _edit_skus(data, edit.skus)
        if edit.specImageGroupIndex is not None:
            move_spec_image_group(data, edit.specImageGroupIndex)
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
                if "small_pic" in linked[0]:
                    linked[0]["small_pic"] = item.url
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
        if edit.specImages is not None or edit.specImageGroupIndex is not None or edit.skus is not None or edit.specStructure is not None:
            raise ProductRequestError("拼多多数据包的规格编辑尚未接入")
        if edit.category is not None or edit.attributes is not None:
            target = _mapping(data.setdefault("douyinTarget", {}), "抖店类目数据格式无效")
            if edit.category is not None:
                levels = [{"id": item.id, "name": item.name.strip()} for item in edit.category]
                if any(not level["name"] or not int(level["id"]) for level in levels):
                    raise ProductRequestError("抖店类目无效")
                old_parts = target.get("category")
                old_ids = [item.get("id") for item in old_parts if isinstance(item, dict)] if isinstance(old_parts, list) else []
                if old_ids != [level["id"] for level in levels]:
                    target["attributes"] = {}
                target["category"] = levels
            if edit.attributes is not None:
                parts = target.get("category")
                if (not isinstance(parts, list) or not 1 <= len(parts) <= 4 or any(
                    not isinstance(part, dict) or not isinstance(part.get("id"), str)
                    or not re.fullmatch(r"[0-9]{1,20}", part["id"]) or not part["id"].strip("0")
                    or not isinstance(part.get("name"), str) or not part["name"].strip() for part in parts
                )):
                    raise ProductRequestError("请先选择抖店类目")
                values = _mapping(target.setdefault("attributes", {}), "抖店属性数据格式无效")
                for item in edit.attributes:
                    if item.values:
                        values[item.id] = {"name": item.name, "values": [value.model_dump() for value in item.values]}
                    else:
                        values.pop(item.id, None)
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
