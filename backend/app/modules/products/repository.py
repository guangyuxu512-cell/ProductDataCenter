from __future__ import annotations

from sqlalchemy import Connection, Engine, text

from .queries import ProductListOptions, build_product_list_queries
from .errors import DraftStatusUnavailable


class ProductRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, options: ProductListOptions, *, include_edits: bool = False) -> dict:
        listing, count = build_product_list_queries(options, include_edits=include_edits)
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
            skus = conn.execute(text("""SELECT sku_id, sku_name, current_price, image_rel_path, sort_order
                FROM product_skus WHERE product_id=:id ORDER BY sort_order, sku_id"""), {"id": product_id}).mappings().all()
            images = conn.execute(text("""SELECT image_type, sort_order, rel_path, source_url
                FROM product_images WHERE product_id=:id ORDER BY image_type, sort_order"""), {"id": product_id}).mappings().all()
            return {"product": product, "skus": skus, "images": images}

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

    @staticmethod
    def _export_rows(conn: Connection, product_ids: list[str]) -> list[dict]:
        return [dict(row) for row in conn.execute(text("""SELECT product_id, source_platform, source_product_id,
                title, captured_at, uu_rel_path, uu_sha256, uu_json::text AS uu_text FROM products
                WHERE product_id=ANY(CAST(:ids AS text[])) AND uu_json IS NOT NULL
                ORDER BY array_position(CAST(:ids AS text[]),product_id)"""), {"ids": product_ids}).mappings()]

    def export_rows(self, product_ids: list[str]) -> list[dict]:
        with self.engine.connect() as conn:
            return self._export_rows(conn, product_ids)

    def exportable_rows(self, product_ids: list[str]) -> list[dict]:
        # Check drafts and read source records in the same snapshot. A draft saved
        # concurrently becomes visible to the next request, never halfway through this one.
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True) as conn, conn.begin():
            status = conn.execute(text("""SELECT to_regclass('public.product_workbench_edits') IS NOT NULL AS present,
                CASE WHEN to_regclass('public.product_workbench_edits') IS NULL THEN true ELSE
                has_table_privilege('public.product_workbench_edits', 'SELECT') END AS readable""")).mappings().one()
            if not status["present"]:
                return self._export_rows(conn, product_ids)
            if not status["readable"]:
                raise DraftStatusUnavailable()
            if conn.execute(text("""SELECT 1 FROM product_workbench_edits
                WHERE product_id=ANY(CAST(:ids AS text[])) LIMIT 1"""), {"ids": product_ids}).first():
                from .errors import ProductDraftPending
                raise ProductDraftPending()
            return self._export_rows(conn, product_ids)

    def image(self, product_id: str, kind: str, position: int):
        with self.engine.connect() as conn:
            return conn.execute(text("""SELECT rel_path, source_url FROM product_images
                WHERE product_id=:id AND image_type=:kind AND sort_order=:position"""),
                {"id": product_id, "kind": kind, "position": position}).mappings().first()
