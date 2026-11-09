from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from .queries import ProductListOptions, build_product_list_queries
from .pdd_categories import source_category_path
from .source_attributes import source_attributes
from .manual import manual_package
from .editing import _sku_key, _validate_pdd_spec_images, apply_edit, move_spec_image_group
from .errors import ProductEditConflict, ProductNotFound, ProductRequestError


def _original_category_id(levels) -> str | None:
    """Use the deepest ID present in a Douyin source package, without guessing."""
    for value in levels:
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            return None
        if value.isascii() and value.isdigit() and not value.strip("0"):
            continue
        if not re.fullmatch(r"[0-9]{1,20}", value):
            return None
        return value
    return None


def _spec_image_values(value_groups, sku_groups, index):
    group = value_groups[index] if isinstance(value_groups, list) and index < len(value_groups) else {}
    values = group.get("spec_values", []) if isinstance(group, dict) else []
    sku_group = sku_groups[index] if isinstance(sku_groups, list) and index < len(sku_groups) else {}
    items = sku_group.get("spec_item_list", []) if isinstance(sku_group, dict) else []
    links = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("spec_item_id") is not None:
            key = str(item["spec_item_id"])
            links.setdefault(key, []).append(item)
    result = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        key = str(item["id"])
        matches = links.get(key, [])
        linked = matches[0] if len(matches) == 1 else {}
        result.append({"id": key, "name": str(item.get("name", "")),
            "url": str(item.get("img_url") or linked.get("big_pic") or linked.get("small_pic") or "")})
    return result


class ProductRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create_manual(self, title: str, draft_seed: str | None = None, edit=None) -> str:
        product_id = "manual:" + str(uuid4().int)
        package, sku_id = manual_package(title, draft_seed)
        with self.engine.begin() as conn:
            saved = conn.execute(text("""INSERT INTO products
                (product_id, source_platform, source_product_id, title, title_status, sku_count, captured_at, uu_json)
                VALUES (:id, 'douyin', NULL, :title, '手动创建', 1, now(), CAST(:package AS jsonb))
                RETURNING uu_json::text"""),
                {"id": product_id, "title": title, "package": json.dumps(package, ensure_ascii=False)}).scalar_one()
            conn.execute(text("""INSERT INTO product_skus(product_id, sku_id, sku_name, sort_order)
                VALUES (:id, :sku, '规格: 默认', 0)"""), {"id": product_id, "sku": sku_id})
            if edit is not None:
                version = hashlib.sha256(saved.encode("utf-8")).hexdigest()
                self.save_edit(product_id, edit.model_copy(update={"expectedVersion": version}), conn=conn, mark_modified=False)
        return product_id

    def list(self, options: ProductListOptions) -> dict:
        listing, count = build_product_list_queries(options)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        ) as conn, conn.begin():
            items = conn.exec_driver_sql(*listing.dbapi()).mappings().all()
            total = conn.exec_driver_sql(*count.dbapi()).scalar_one() if count else None
        return {"items": [self._display_source_category(item) for item in items],
                "total": total, "totalIncluded": count is not None,
                "limit": options.limit, "offset": options.offset}

    @staticmethod
    def _display_source_category(row) -> dict:
        product = dict(row)
        product["category_path"] = source_category_path(product["source_platform"], product["category_path"] or "")
        return product

    def detail(self, product_id: str) -> dict | None:
        listing, _ = build_product_list_queries(ProductListOptions(product_id=product_id, include_total=False))
        # Exact internal key for details: source IDs are only an explicit list filter.
        sql = listing.sql.replace("(p.product_id = $1 OR p.source_product_id = $1)", "p.product_id = $1")
        from .queries import Query
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        ) as conn, conn.begin():
            product = conn.exec_driver_sql(*Query(sql, listing.params).dbapi()).mappings().first()
            if product is None:
                return None
            product = self._display_source_category(product)
            source_category_id = None
            attributes = []
            target_category, target_attributes = [], []
            if product["source_platform"] == "douyin":
                # Read only the original category and attribute fields for this exact product;
                # the paginated product list must not load package JSON.
                levels = conn.execute(text("""SELECT uu_json #>> '{goodsInfo,catId4}',
                    uu_json #>> '{goodsInfo,catId3}', uu_json #>> '{goodsInfo,catId2}',
                    uu_json #>> '{goodsInfo,catId1}', uu_json #> '{category_properties_value,value}',
                    uu_json #> '{goodsDetailInfo,product_format}' FROM products WHERE product_id=:id"""),
                    {"id": product_id}).one()
                source_category_id = _original_category_id(levels[:4])
                attributes = source_attributes(levels[4], levels[5])
            elif product["source_platform"] == "pinduoduo":
                target, pdd_values, pdd_formats, pdd_properties = conn.execute(text("""SELECT
                    uu_json #> '{douyinTarget}', uu_json #> '{category_properties_value,value}',
                    uu_json #> '{goodsDetailInfo,product_format}', uu_json #> '{product,properties}'
                    FROM products WHERE product_id=:id"""), {"id": product_id}).one()
                attributes = source_attributes(pdd_values, pdd_formats, pdd_properties)
                if isinstance(target, dict):
                    parts = target.get("category")
                    if isinstance(parts, list) and 0 < len(parts) <= 4 and all(
                        isinstance(item, dict) and isinstance(item.get("id"), str)
                        and re.fullmatch(r"[0-9]{1,20}", item["id"]) and item["id"].strip("0")
                        and isinstance(item.get("name"), str) and 0 < len(item["name"]) <= 200 for item in parts
                    ):
                        target_category = [{"id": item["id"], "name": item["name"]} for item in parts]
                    stored = target.get("attributes")
                    if target_category and isinstance(stored, dict):
                        for identity, item in list(stored.items())[:300]:
                            if not isinstance(identity, str) or not isinstance(item, dict) or not isinstance(item.get("name"), str):
                                continue
                            values = item.get("values")
                            if isinstance(values, list):
                                value_items = [{"valueId": str(value.get("valueId") or "0"), "name": value["name"]}
                                               for value in values
                                               if isinstance(value, dict) and isinstance(value.get("name"), str)]
                                names = [value["name"] for value in value_items]
                                # An explicitly cleared value must remain distinguishable
                                # from a value that has never been mapped.
                                target_attributes.append({"id": identity, "name": item["name"],
                                                          "values": names, "valueItems": value_items})
            skus = conn.execute(text("""SELECT sku_id, sku_name, current_price, image_rel_path, sort_order
                FROM product_skus WHERE product_id=:id ORDER BY sort_order, sku_id"""), {"id": product_id}).mappings().all()
            images = conn.execute(text("""SELECT image_type, sort_order, rel_path, source_url
                FROM product_images WHERE product_id=:id ORDER BY image_type, sort_order"""), {"id": product_id}).mappings().all()
            return {"product": product, "skus": skus, "images": images,
                    "sourceCategoryId": source_category_id, "sourceAttributes": attributes,
                    "targetCategory": target_category, "targetAttributes": target_attributes}

    def groups(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [self._group(row) for row in conn.execute(text("""SELECT g.group_id, g.group_name,
                g.created_at, g.updated_at, count(p.product_id)::integer AS product_count
                FROM product_groups g LEFT JOIN products p ON p.group_id=g.group_id
                GROUP BY g.group_id ORDER BY lower(g.group_name), g.created_at""")).mappings()]

    def group_exists(self, group_id) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM product_groups WHERE group_id=:id)"),
                                     {"id": group_id}).scalar_one())

    @staticmethod
    def _group(row) -> dict:
        return {"groupId": row["group_id"], "name": row["group_name"],
                "productCount": row.get("product_count", 0),
                "createdAt": row.get("created_at"), "updatedAt": row.get("updated_at")}

    def create_group(self, conn: Connection, name: str) -> dict:
        row = conn.execute(text("""INSERT INTO product_groups(group_name) VALUES (:name)
            RETURNING group_id, group_name, created_at, updated_at"""), {"name": name}).mappings().one()
        return self._group(row)

    def rename_group(self, conn: Connection, group_id, name: str) -> dict | None:
        row = conn.execute(text("""UPDATE product_groups SET group_name=:name WHERE group_id=:id
            RETURNING group_id, group_name, created_at, updated_at,
            (SELECT count(*)::integer FROM products WHERE group_id=:id) AS product_count"""),
            {"id": group_id, "name": name}).mappings().first()
        return self._group(row) if row else None

    def lock_group(self, conn: Connection, group_id):
        return conn.execute(text("SELECT group_id, group_name FROM product_groups WHERE group_id=:id FOR UPDATE"),
                            {"id": group_id}).mappings().first()

    def delete_group(self, conn: Connection, group_id) -> int:
        count = conn.execute(text("SELECT count(*)::integer FROM products WHERE group_id=:id"), {"id": group_id}).scalar_one()
        conn.execute(text("DELETE FROM product_groups WHERE group_id=:id"), {"id": group_id})
        return count

    def assign_group(self, conn: Connection, product_ids: list[str], group_id) -> list[str]:
        return list(conn.execute(text("""UPDATE products SET group_id=:group_id
            WHERE product_id=ANY(CAST(:ids AS text[])) RETURNING product_id"""),
            {"ids": product_ids, "group_id": group_id}).scalars())

    def delete_products(self, product_ids: list[str]) -> list[str]:
        # Collector-owned foreign keys cascade SKU, image and precheck rows.
        # Image files are deliberately left alone: URLs may be shared.
        with self.engine.begin() as conn:
            return list(conn.execute(text("""DELETE FROM products
                WHERE product_id=ANY(CAST(:ids AS text[])) RETURNING product_id"""),
                {"ids": product_ids}).scalars())

    def export_rows(self, product_ids: list[str]) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text("""SELECT product_id, source_platform, source_product_id,
                title, captured_at, uu_rel_path, uu_sha256, uu_json::text AS uu_text FROM products
                WHERE product_id=ANY(CAST(:ids AS text[])) AND uu_json IS NOT NULL
                ORDER BY array_position(CAST(:ids AS text[]),product_id)"""), {"ids": product_ids}).mappings()]

    def category_paths(self, product_ids: list[str]) -> list[dict]:
        """Read only the category IDs needed for display; never load entire packages."""
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        ) as conn, conn.begin():
            return [dict(row) for row in conn.execute(text("""SELECT product_id, source_platform,
                uu_json #>> '{goodsInfo,catId1}' AS cat1, uu_json #>> '{goodsInfo,catId2}' AS cat2,
                uu_json #>> '{goodsInfo,catId3}' AS cat3, uu_json #>> '{goodsInfo,catId4}' AS cat4
                FROM products WHERE product_id=ANY(CAST(:ids AS text[]))
                ORDER BY array_position(CAST(:ids AS text[]),product_id)"""),
                {"ids": product_ids}).mappings()]

    def edit_snapshot(self, product_id: str) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT uu_json::text AS package, source_platform FROM products WHERE product_id=:id"),
                               {"id": product_id}).mappings().first()
            projection_ids = None
            if row is not None and row["source_platform"] in {"pinduoduo", "pdd"}:
                projection_ids = set(conn.execute(text("SELECT sku_id FROM product_skus WHERE product_id=:id"),
                                                  {"id": product_id}).scalars())
        if row is None:
            raise ProductNotFound()
        if not row["package"]:
            raise ProductRequestError("商品数据包缺失，无法编辑")
        package = json.loads(row["package"])
        spec_block = package.get("spec_detail_value") if isinstance(package, dict) else None
        groups = spec_block.get("value", []) if isinstance(spec_block, dict) else []
        sku_block = package.get("goodsSkuInfo") if isinstance(package, dict) else None
        sku_groups = sku_block.get("sku_detail", []) if isinstance(sku_block, dict) else []

        first = groups[0] if isinstance(groups, list) and groups and isinstance(groups[0], dict) else {}
        spec_images = _spec_image_values(groups, sku_groups, 0)
        spec_groups = []
        for index, group in enumerate(groups if isinstance(groups, list) else []):
            if not isinstance(group, dict):
                spec_groups.append({"index": index, "name": "", "values": [], "movable": False})
                continue
            values = group.get("spec_values")
            if not isinstance(values, list):
                spec_groups.append({"index": index, "name": str(group.get("name") or ""), "values": [], "movable": False})
                continue
            movable = False
            if index:
                try:
                    move_spec_image_group(deepcopy(package), index)
                    movable = True
                except ProductRequestError:
                    pass
            spec_groups.append({"index": index, "name": str(group.get("name") or ""),
                "values": _spec_image_values(groups, sku_groups, index),
                "movable": movable})
        detail = sku_block.get("spec_detail") if isinstance(sku_block, dict) else None
        rows = detail.get("value", []) if isinstance(detail, dict) else []
        goods = package.get("goodsInfo") if isinstance(package, dict) else None
        sku_map = goods.get("skuInfoMap", {}) if isinstance(goods, dict) else {}
        sku_rows = []
        if isinstance(rows, list) and isinstance(sku_map, dict):
            for item in rows:
                if not isinstance(item, dict) or not isinstance(item.get("spec_detail_ids"), list):
                    continue
                ids = [str(value) for value in item["spec_detail_ids"]]
                key = "_".join(ids)
                source = sku_map.get(key)
                if not ids or not isinstance(source, dict):
                    continue
                source_id = _sku_key(source, key)
                stock = item.get("stock_info")
                sku_rows.append({"skuId": str(source_id), "specIds": ids, "price": str(item.get("price") or ""),
                    "stock": stock.get("stock_num") if isinstance(stock, dict) else None,
                    "enabled": item.get("sku_status") if isinstance(item.get("sku_status"), bool) else None,
                    "merchantCode": str(item.get("merchant_code") or "")})
        spec_images_editable = True
        if row["source_platform"] in {"pinduoduo", "pdd"}:
            try:
                if isinstance(package.get("product"), dict):
                    raise ProductRequestError("原始拼多多包未接入规格图编辑")
                _validate_pdd_spec_images(package)
                if {item["skuId"] for item in sku_rows} != projection_ids:
                    raise ProductRequestError("拼多多 SKU 记录与数据包无法安全对应")
            except ProductRequestError:
                spec_images_editable = False
        return {"version": hashlib.sha256(row["package"].encode("utf-8")).hexdigest(),
                "specImageGroup": str(first.get("name") or ""), "specImages": spec_images,
                "specGroups": spec_groups, "specImagesEditable": spec_images_editable, "skus": sku_rows}

    def save_edit(self, product_id: str, edit, conn: Connection | None = None, mark_modified: bool = True) -> dict:
        with (nullcontext(conn) if conn is not None else self.engine.begin()) as conn:
            row = conn.execute(text("""SELECT source_platform, uu_json::text AS package, title_status
                FROM products WHERE product_id=:id FOR UPDATE"""), {"id": product_id}).mappings().first()
            if row is None:
                raise ProductNotFound()
            if not row["package"]:
                raise ProductRequestError("商品数据包缺失，无法编辑")
            version = hashlib.sha256(row["package"].encode("utf-8")).hexdigest()
            if version != edit.expectedVersion:
                raise ProductEditConflict()
            original_package = json.loads(row["package"])
            package = apply_edit(original_package, row["source_platform"], edit)
            if row["source_platform"] in {"pinduoduo", "pdd"} and edit.specImages is not None:
                sku_map = package["goodsInfo"]["skuInfoMap"]
                expected_ids = {_sku_key(source, key) for key, source in sku_map.items()}
                actual_ids = set(conn.execute(text("SELECT sku_id FROM product_skus WHERE product_id=:id"),
                                              {"id": product_id}).scalars())
                if expected_ids != actual_ids:
                    raise ProductRequestError("拼多多 SKU 记录与数据包无法安全对应")
            original_sku_paths = {}
            original_sku_urls = {}
            if edit.specStructure is not None:
                original_sku_paths = {item["sku_id"]: item["image_rel_path"] for item in conn.execute(text(
                    "SELECT sku_id,image_rel_path FROM product_skus WHERE product_id=:id"), {"id": product_id}).mappings()}
                original_groups = original_package.get("spec_detail_value", {}).get("value", [])
                original_info = original_package.get("goodsSkuInfo", {})
                first_images = {item["id"]: item["url"] for item in
                    _spec_image_values(original_groups, original_info.get("sku_detail", []), 0)}
                original_map = original_package.get("goodsInfo", {}).get("skuInfoMap", {})
                for item in original_info.get("spec_detail", {}).get("value", []):
                    ids = [str(value) for value in item.get("spec_detail_ids", [])]
                    key = "_".join(ids)
                    source = original_map.get(key)
                    if ids and isinstance(source, dict):
                        original_sku_urls[_sku_key(source, key)] = first_images.get(ids[0], "")
            status = row["title_status"] or ""
            if mark_modified and not status.endswith("商品库已修改"):
                status = f"{status} | 商品库已修改" if status else "商品库已修改"
            params = {"id": product_id, "package": json.dumps(package, ensure_ascii=False, separators=(",", ":")),
                      "title": edit.title, "status": status}
            sql = "UPDATE products SET uu_json=CAST(:package AS jsonb), title_status=:status"
            if edit.title is not None:
                sql += ", title=:title"
            if edit.category is not None and row["source_platform"] == "douyin":
                for index in range(1, 5):
                    params[f"level{index}"] = edit.category[index - 1].name if index <= len(edit.category) else ""
                    sql += f", category_level_{index}=:level{index}"
                params["path"] = " → ".join(item.name for item in edit.category)
                params["leaf"] = edit.category[-1].id
                sql += ", category_path=:path, category_leaf_id=:leaf"
            for kind, urls in (("main", edit.mainImages), ("detail", edit.detailImages)):
                if urls is None:
                    continue
                old = conn.execute(text("""SELECT source_url, rel_path FROM product_images
                    WHERE product_id=:id AND image_type=:kind"""), {"id": product_id, "kind": kind}).mappings()
                paths = {item["source_url"]: item["rel_path"] for item in old if item["source_url"] and item["rel_path"]}
                conn.execute(text("DELETE FROM product_images WHERE product_id=:id AND image_type=:kind"),
                             {"id": product_id, "kind": kind})
                for index, url in enumerate(urls):
                    conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                        VALUES (:id,:kind,:position,:path,:url)"""),
                        {"id": product_id, "kind": kind, "position": index, "path": paths.get(url, ""), "url": url})
                params[f"{kind}_count"] = len(urls)
                sql += f", {kind}_image_count=:{kind}_count"
            if edit.specImages is not None or edit.specImageGroupIndex is not None or edit.specStructure is not None:
                groups = package["spec_detail_value"]["value"]
                sku_groups = package["goodsSkuInfo"]["sku_detail"]
                image_groups = [_spec_image_values(groups, sku_groups, index) for index in range(len(groups))]
                sku_urls = list(dict.fromkeys(item["url"] for group in image_groups for item in group
                    if item["url"].startswith(("http://", "https://"))))
                old = list(conn.execute(text("""SELECT source_url, rel_path FROM product_images
                    WHERE product_id=:id AND image_type='sku' ORDER BY sort_order"""), {"id": product_id}).mappings())
                paths = {item["source_url"]: item["rel_path"] for item in old if item["source_url"] and item["rel_path"]}
                entries = [(url, paths.get(url, "")) for url in sku_urls]
                if row["source_platform"] in {"pinduoduo", "pdd"}:
                    original_groups = original_package["spec_detail_value"]["value"]
                    original_sku_groups = original_package["goodsSkuInfo"]["sku_detail"]
                    original_images = {item["id"]: item["url"] for item in
                                       _spec_image_values(original_groups, original_sku_groups, 0)}
                    replacements = {}
                    for change in edit.specImages or []:
                        original_url = original_images.get(change.specId)
                        if original_url:
                            replacements.setdefault(original_url, []).append(change.url)
                    # Preserve every unrelated row, even duplicate URLs and local-only images.
                    # A changed URL is removed only when no remaining spec references it.
                    surviving = {item["source_url"] for item in old if item["source_url"] and
                                 not (item["source_url"] in replacements and item["source_url"] not in sku_urls)}
                    entries = []
                    for item in old:
                        old_url = item["source_url"] or ""
                        if old_url in replacements and old_url not in sku_urls:
                            for new_url in replacements[old_url]:
                                if new_url and new_url in sku_urls and new_url not in surviving:
                                    entries.append((new_url, paths.get(new_url, "")))
                                    surviving.add(new_url)
                        else:
                            entries.append((old_url, item["rel_path"] or ""))
                    for url in sku_urls:
                        if url not in surviving:
                            entries.append((url, paths.get(url, "")))
                            surviving.add(url)
                conn.execute(text("DELETE FROM product_images WHERE product_id=:id AND image_type='sku'"), {"id": product_id})
                for index, (url, image_path) in enumerate(entries):
                    conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                        VALUES (:id,'sku',:position,:path,:url)"""),
                        {"id": product_id, "position": index, "path": image_path, "url": url})
                params["sku_count_images"] = len(entries)
                sql += ", sku_image_count=:sku_count_images"
                spec_to_url = {item["id"]: item["url"] for item in image_groups[0]}
                sku_map = package.get("goodsInfo", {}).get("skuInfoMap", {})
                for sku_row in package.get("goodsSkuInfo", {}).get("spec_detail", {}).get("value", []):
                    if not isinstance(sku_row, dict) or not isinstance(sku_row.get("spec_detail_ids"), list):
                        continue
                    ids = [str(value) for value in sku_row["spec_detail_ids"]]
                    if (row["source_platform"] in {"pinduoduo", "pdd"} and edit.specImages is not None and
                            (not ids or ids[0] not in {item.specId for item in edit.specImages})):
                        continue
                    changed = spec_to_url.get(ids[0]) if ids else None
                    source = sku_map.get("_".join(ids), {}) if isinstance(sku_map, dict) else {}
                    source_id = _sku_key(source, "_".join(ids)) if isinstance(source, dict) else None
                    if changed is not None and source_id is not None:
                        conn.execute(text("UPDATE product_skus SET image_rel_path=:path WHERE product_id=:id AND sku_id=:sku_id"),
                                     {"id": product_id, "sku_id": str(source_id), "path": paths.get(changed, "")})
            if edit.skus is not None or edit.specStructure is not None:
                params["sku_count"] = len(package["goodsSkuInfo"]["spec_detail"]["value"])
                sql += ", sku_count=:sku_count"
                if not package["goodsInfo"]["skuInfoMap"]:
                    sql += ", current_price_min=NULL, current_price_max=NULL"
            sql += " WHERE product_id=:id RETURNING uu_json::text"
            saved = conn.execute(text(sql), params).scalar_one()
            if edit.skus is not None:
                source_map = original_package["goodsInfo"]["skuInfoMap"]
                ids = [_sku_key(value, key)
                       for key, value in source_map.items() if isinstance(value, dict)]
                for change in edit.skus:
                    key = "_".join(change.specIds)
                    source = source_map[key]
                    source_id = _sku_key(source, key)
                    if ids.count(source_id) != 1:
                        raise ProductRequestError("SKU 来源标识不唯一，无法安全保存")
                    if change.delete:
                        conn.execute(text("DELETE FROM product_skus WHERE product_id=:id AND sku_id=:sku_id"),
                                     {"id": product_id, "sku_id": source_id})
                    elif change.price is not None:
                        conn.execute(text("UPDATE product_skus SET current_price=:price WHERE product_id=:id AND sku_id=:sku_id"),
                                     {"id": product_id, "sku_id": source_id, "price": change.price})
            if edit.specStructure is not None:
                old_map = original_package["goodsInfo"]["skuInfoMap"]
                old_rows = original_package["goodsSkuInfo"]["spec_detail"]["value"]
                old_ids = [_sku_key(old_map["_".join(map(str, item["spec_detail_ids"]))],
                                    "_".join(map(str, item["spec_detail_ids"]))) for item in old_rows]
                new_map = package["goodsInfo"]["skuInfoMap"]
                new_rows = package["goodsSkuInfo"]["spec_detail"]["value"]
                new_ids = [_sku_key(new_map["_".join(map(str, item["spec_detail_ids"]))],
                                    "_".join(map(str, item["spec_detail_ids"]))) for item in new_rows]
                if len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids):
                    raise ProductRequestError("SKU 来源标识不唯一，无法安全保存")
                if any(sku_id in original_sku_paths for sku_id in set(new_ids) - set(old_ids)):
                    raise ProductRequestError("新增 SKU 与已有记录冲突，无法安全保存")
                for sku_id in set(old_ids) - set(new_ids):
                    conn.execute(text("DELETE FROM product_skus WHERE product_id=:id AND sku_id=:sku_id"),
                                 {"id": product_id, "sku_id": sku_id})
                value_names = [{value["id"]: value["name"] for value in group["spec_values"]}
                               for group in package["spec_detail_value"]["value"]]
                group_names = [group["name"] for group in package["spec_detail_value"]["value"]]
                for index, (sku_id, item) in enumerate(zip(new_ids, new_rows, strict=True)):
                    ids = [str(value) for value in item["spec_detail_ids"]]
                    name = " / ".join(f"{group_names[i]}: {value_names[i][value]}" for i, value in enumerate(ids))
                    image_url = spec_to_url.get(ids[0], "")
                    price = item.get("price")
                    try:
                        price = Decimal(str(price))
                        if not price.is_finite() or price < 0:
                            price = None
                    except InvalidOperation:
                        price = None
                    image_path = paths.get(image_url)
                    if image_path is None and original_sku_urls.get(sku_id) == image_url:
                        image_path = original_sku_paths.get(sku_id, "")
                    conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,image_rel_path,sort_order)
                        VALUES (:id,:sku_id,:name,:price,:path,:position)
                        ON CONFLICT (product_id,sku_id) DO UPDATE SET sku_name=excluded.sku_name,
                        current_price=excluded.current_price,image_rel_path=excluded.image_rel_path,sort_order=excluded.sort_order"""),
                        {"id": product_id, "sku_id": sku_id, "name": name, "price": price,
                         "path": image_path or "", "position": index})
            saved_version = hashlib.sha256(saved.encode("utf-8")).hexdigest()
            conn.execute(text("UPDATE products SET uu_sha256=:version WHERE product_id=:id"),
                         {"id": product_id, "version": saved_version})
            return {"version": saved_version}

    def set_default_brand(self, product_id: str, selection: dict, *, force: bool = False,
                          mark_modified: bool = False) -> str:
        """Write only the real platform brand field and let the queue trigger recheck it."""
        with self.engine.begin() as conn:
            row = conn.execute(text("""SELECT source_platform, title_status, uu_json AS package
                FROM products WHERE product_id=:id FOR UPDATE"""), {"id": product_id}).mappings().first()
            if row is None or not isinstance(row["package"], dict):
                return "missing"
            status = str(row["title_status"] or "")
            if not force and status.endswith("商品库已修改"):
                return "manual"
            package = deepcopy(row["package"])
            field_id = str(selection["fieldId"])
            expected = {"valueId": str(selection["valueId"]), "name": str(selection["valueName"])}
            if row["source_platform"] == "douyin":
                block = package.setdefault("category_properties_value", {"value": {}})
                values = block.get("value") if isinstance(block, dict) else None
                if not isinstance(values, dict):
                    return "unsupported"
                current = values.get(field_id)
                if (isinstance(current, list) and len(current) == 1 and isinstance(current[0], dict)
                        and str(current[0].get("value_id") or "") == expected["valueId"]
                        and current[0].get("value_name") == expected["name"]):
                    return "already"
                values[field_id] = [{"diy_type": 0, "k": str(selection["fieldName"]),
                                     "value_id": expected["valueId"], "value_name": expected["name"]}]
            elif row["source_platform"] in {"pinduoduo", "pdd"}:
                target = package.get("douyinTarget")
                attributes = target.get("attributes") if isinstance(target, dict) else None
                if not isinstance(attributes, dict):
                    return "unsupported"
                current = attributes.get(field_id)
                if (isinstance(current, dict) and current.get("values") == [expected]):
                    return "already"
                attributes[field_id] = {"name": str(selection["fieldName"]), "values": [expected]}
            else:
                return "unsupported"
            if mark_modified and not status.endswith("商品库已修改"):
                status = f"{status} | 商品库已修改" if status else "商品库已修改"
            saved = conn.execute(text("""UPDATE products SET uu_json=CAST(:package AS jsonb), title_status=:status
                WHERE product_id=:id RETURNING uu_json::text"""), {
                    "id": product_id, "status": status,
                    "package": json.dumps(package, ensure_ascii=False, separators=(",", ":")),
                }).scalar_one()
            conn.execute(text("UPDATE products SET uu_sha256=:version WHERE product_id=:id"), {
                "id": product_id, "version": hashlib.sha256(saved.encode("utf-8")).hexdigest(),
            })
            return "updated"

    def image(self, product_id: str, kind: str, position: int):
        with self.engine.connect() as conn:
            return conn.execute(text("""SELECT rel_path, source_url FROM product_images
                WHERE product_id=:id AND image_type=:kind AND sort_order=:position"""),
                {"id": product_id, "kind": kind, "position": position}).mappings().first()
