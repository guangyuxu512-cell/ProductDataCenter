from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from sqlalchemy import Connection, Engine, text

from .queries import ProductListOptions, build_product_list_queries
from .source_attributes import source_attributes
from .editing import apply_edit, move_spec_image_group
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


class ProductRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, options: ProductListOptions) -> dict:
        listing, count = build_product_list_queries(options)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        ) as conn, conn.begin():
            items = conn.exec_driver_sql(*listing.dbapi()).mappings().all()
            total = conn.exec_driver_sql(*count.dbapi()).scalar_one() if count else None
        return {"items": items, "total": total, "totalIncluded": count is not None,
                "limit": options.limit, "offset": options.offset}

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
            source_category_id = None
            attributes = []
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
            skus = conn.execute(text("""SELECT sku_id, sku_name, current_price, image_rel_path, sort_order
                FROM product_skus WHERE product_id=:id ORDER BY sort_order, sku_id"""), {"id": product_id}).mappings().all()
            images = conn.execute(text("""SELECT image_type, sort_order, rel_path, source_url
                FROM product_images WHERE product_id=:id ORDER BY image_type, sort_order"""), {"id": product_id}).mappings().all()
            return {"product": product, "skus": skus, "images": images,
                    "sourceCategoryId": source_category_id, "sourceAttributes": attributes}

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

    def export_rows(self, product_ids: list[str]) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text("""SELECT product_id, source_platform, source_product_id,
                title, captured_at, uu_rel_path, uu_sha256, uu_json::text AS uu_text FROM products
                WHERE product_id=ANY(CAST(:ids AS text[])) AND uu_json IS NOT NULL
                ORDER BY array_position(CAST(:ids AS text[]),product_id)"""), {"ids": product_ids}).mappings()]

    def edit_snapshot(self, product_id: str) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT uu_json::text AS package FROM products WHERE product_id=:id"),
                               {"id": product_id}).mappings().first()
        if row is None:
            raise ProductNotFound()
        if not row["package"]:
            raise ProductRequestError("商品数据包缺失，无法编辑")
        package = json.loads(row["package"])
        spec_block = package.get("spec_detail_value") if isinstance(package, dict) else None
        groups = spec_block.get("value", []) if isinstance(spec_block, dict) else []
        sku_block = package.get("goodsSkuInfo") if isinstance(package, dict) else None
        sku_groups = sku_block.get("sku_detail", []) if isinstance(sku_block, dict) else []

        def image_values(index, values):
            group = sku_groups[index] if isinstance(sku_groups, list) and index < len(sku_groups) else {}
            items = group.get("spec_item_list", []) if isinstance(group, dict) else []
            links = {}
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and item.get("spec_item_id") is not None:
                    key = str(item["spec_item_id"])
                    links.setdefault(key, []).append(item)
            result = []
            for item in values:
                if not isinstance(item, dict) or item.get("id") is None:
                    continue
                key = str(item["id"])
                matches = links.get(key, [])
                linked = matches[0] if len(matches) == 1 else {}
                result.append({"id": key, "name": str(item.get("name", "")),
                    "url": str(item.get("img_url") or linked.get("big_pic") or linked.get("small_pic") or "")})
            return result

        first = groups[0] if isinstance(groups, list) and groups and isinstance(groups[0], dict) else {}
        items = first.get("spec_values", []) if isinstance(first.get("spec_values", []), list) else []
        spec_images = image_values(0, items)
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
                "values": image_values(index, values),
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
                source_id = source.get("sku_id") or source.get("skuId") or source.get("id") or key
                stock = item.get("stock_info")
                sku_rows.append({"skuId": str(source_id), "specIds": ids, "price": str(item.get("price") or ""),
                    "stock": stock.get("stock_num") if isinstance(stock, dict) else None,
                    "enabled": item.get("sku_status") if isinstance(item.get("sku_status"), bool) else None,
                    "merchantCode": str(item.get("merchant_code") or "")})
        return {"version": hashlib.sha256(row["package"].encode("utf-8")).hexdigest(),
                "specImageGroup": str(first.get("name") or ""), "specImages": spec_images,
                "specGroups": spec_groups, "skus": sku_rows}

    def save_edit(self, product_id: str, edit) -> dict:
        with self.engine.begin() as conn:
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
            status = row["title_status"] or ""
            if not status.endswith("商品库已修改"):
                status = f"{status} | 商品库已修改" if status else "商品库已修改"
            params = {"id": product_id, "package": json.dumps(package, ensure_ascii=False, separators=(",", ":")),
                      "title": edit.title, "status": status}
            sql = "UPDATE products SET uu_json=CAST(:package AS jsonb), title_status=:status"
            if edit.title is not None:
                sql += ", title=:title"
            if edit.category is not None:
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
            if edit.specImages is not None or edit.specImageGroupIndex is not None:
                groups = package["spec_detail_value"]["value"]
                sku_urls = list(dict.fromkeys(str(item.get("img_url")) for group in groups if isinstance(group, dict)
                    for item in group.get("spec_values", []) if isinstance(item, dict) and item.get("img_url")
                    and str(item.get("img_url")).startswith(("http://", "https://"))))
                old = conn.execute(text("""SELECT source_url, rel_path FROM product_images
                    WHERE product_id=:id AND image_type='sku'"""), {"id": product_id}).mappings()
                paths = {item["source_url"]: item["rel_path"] for item in old if item["source_url"] and item["rel_path"]}
                conn.execute(text("DELETE FROM product_images WHERE product_id=:id AND image_type='sku'"), {"id": product_id})
                for index, url in enumerate(sku_urls):
                    conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                        VALUES (:id,'sku',:position,:path,:url)"""),
                        {"id": product_id, "position": index, "path": paths.get(url, ""), "url": url})
                params["sku_count_images"] = len(sku_urls)
                sql += ", sku_image_count=:sku_count_images"
                spec_to_url = {str(item.get("id")): str(item.get("img_url") or "")
                               for item in groups[0].get("spec_values", []) if isinstance(item, dict)}
                sku_map = package.get("goodsInfo", {}).get("skuInfoMap", {})
                for sku_row in package.get("goodsSkuInfo", {}).get("spec_detail", {}).get("value", []):
                    if not isinstance(sku_row, dict) or not isinstance(sku_row.get("spec_detail_ids"), list):
                        continue
                    ids = [str(value) for value in sku_row["spec_detail_ids"]]
                    changed = spec_to_url.get(ids[0]) if ids else None
                    source = sku_map.get("_".join(ids), {}) if isinstance(sku_map, dict) else {}
                    source_id = source.get("sku_id") or source.get("skuId") or source.get("id") if isinstance(source, dict) else None
                    if changed is not None and source_id is not None:
                        conn.execute(text("UPDATE product_skus SET image_rel_path=:path WHERE product_id=:id AND sku_id=:sku_id"),
                                     {"id": product_id, "sku_id": str(source_id), "path": paths.get(changed, "")})
            if edit.skus is not None:
                params["sku_count"] = len(package["goodsSkuInfo"]["spec_detail"]["value"])
                sql += ", sku_count=:sku_count"
                if not package["goodsInfo"]["skuInfoMap"]:
                    sql += ", current_price_min=NULL, current_price_max=NULL"
            sql += " WHERE product_id=:id RETURNING uu_json::text"
            saved = conn.execute(text(sql), params).scalar_one()
            if edit.skus is not None:
                source_map = original_package["goodsInfo"]["skuInfoMap"]
                ids = [str(value.get("sku_id") or value.get("skuId") or value.get("id") or key)
                       for key, value in source_map.items() if isinstance(value, dict)]
                for change in edit.skus:
                    key = "_".join(change.specIds)
                    source = source_map[key]
                    source_id = str(source.get("sku_id") or source.get("skuId") or source.get("id") or key)
                    if ids.count(source_id) != 1:
                        raise ProductRequestError("SKU 来源标识不唯一，无法安全保存")
                    if change.delete:
                        conn.execute(text("DELETE FROM product_skus WHERE product_id=:id AND sku_id=:sku_id"),
                                     {"id": product_id, "sku_id": source_id})
                    elif change.price is not None:
                        conn.execute(text("UPDATE product_skus SET current_price=:price WHERE product_id=:id AND sku_id=:sku_id"),
                                     {"id": product_id, "sku_id": source_id, "price": change.price})
            saved_version = hashlib.sha256(saved.encode("utf-8")).hexdigest()
            conn.execute(text("UPDATE products SET uu_sha256=:version WHERE product_id=:id"),
                         {"id": product_id, "version": saved_version})
            return {"version": saved_version}

    def image(self, product_id: str, kind: str, position: int):
        with self.engine.connect() as conn:
            return conn.execute(text("""SELECT rel_path, source_url FROM product_images
                WHERE product_id=:id AND image_type=:kind AND sort_order=:position"""),
                {"id": product_id, "kind": kind, "position": position}).mappings().first()
