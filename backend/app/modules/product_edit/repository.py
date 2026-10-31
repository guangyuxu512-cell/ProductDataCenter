from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from app.core.exceptions.errors import AppError
from app.modules.products.errors import GroupNotFound, ProductNotFound
from .models import EditorState, ProductDraft, SaveDraft
from .normalize import draft_from_source, source_fingerprint


class EditConflict(AppError):
    code = "PRODUCT_EDIT_CONFLICT"
    message = "商品草稿已被其他操作修改，请重新加载后再保存"
    status_code = 409


class SourceChanged(AppError):
    code = "PRODUCT_EDIT_SOURCE_CHANGED"
    message = "商品来源数据已更新，请重新加载后再保存"
    status_code = 409


class EditorRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def permissions(self) -> tuple[bool, bool]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT
                to_regclass('public.product_workbench_edits') IS NOT NULL AS present,
                CASE WHEN to_regclass('public.product_workbench_edits') IS NULL THEN false ELSE
                    has_table_privilege('public.product_workbench_edits', 'SELECT') AND
                    has_table_privilege('public.product_workbench_edits', 'INSERT') AND
                    has_table_privilege('public.product_workbench_edits', 'UPDATE') END AS draft_write,
                (has_table_privilege('public.products', 'UPDATE') OR
                 has_any_column_privilege('public.products', 'UPDATE')) AS lock_product,
                has_table_privilege('public.products', 'INSERT') AS create_product""")).mappings().one()
        writable = bool(row["present"] and row["draft_write"] and row["lock_product"])
        return writable, bool(writable and row["create_product"])

    @staticmethod
    def _source(conn: Connection, product_id: str, *, lock: bool = False) -> dict:
        statement = """SELECT product_id, source_platform, source_product_id, title, category_path, uu_json
                       FROM products WHERE product_id=:id"""
        if lock:
            statement += " FOR UPDATE"
        row = conn.execute(text(statement), {"id": product_id}).mappings().first()
        if row is None:
            raise ProductNotFound()
        skus = [dict(item) for item in conn.execute(text("""SELECT sku_id, sku_name, current_price, sort_order
            FROM product_skus WHERE product_id=:id ORDER BY sort_order, sku_id"""), {"id": product_id}).mappings()]
        images = [dict(item) for item in conn.execute(text("""SELECT image_type, sort_order, rel_path, source_url
            FROM product_images WHERE product_id=:id ORDER BY image_type, sort_order"""), {"id": product_id}).mappings()]
        return {"product": dict(row), "skus": skus, "images": images}

    @staticmethod
    def _state(source: dict, row) -> EditorState:
        current = source_fingerprint(source)
        if row is None:
            product = source["product"]
            draft = draft_from_source(product, source["skus"], source["images"], product.get("uu_json"))
            return EditorState(productId=product["product_id"], revision=0, sourceFingerprint=current,
                               sourceChanged=False, draft=draft)
        return EditorState(productId=source["product"]["product_id"], revision=row["revision"],
                           sourceFingerprint=current, sourceChanged=row["source_fingerprint"].strip() != current,
                           draft=ProductDraft.model_validate(row["draft"]))

    @staticmethod
    def _saved(conn: Connection, product_id: str):
        return conn.execute(text("""SELECT revision, source_fingerprint, draft
            FROM product_workbench_edits WHERE product_id=:id"""), {"id": product_id}).mappings().first()

    def read(self, product_id: str) -> EditorState:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True) as conn, conn.begin():
            source = self._source(conn, product_id)
            return self._state(source, self._saved(conn, product_id))

    def save(self, product_id: str, body: SaveDraft) -> EditorState:
        with self.engine.begin() as conn:
            source = self._source(conn, product_id, lock=True)
            fingerprint = source_fingerprint(source)
            if fingerprint != body.sourceFingerprint:
                raise SourceChanged()
            existing = self._saved(conn, product_id)
            if (existing["revision"] if existing else 0) != body.expectedRevision:
                raise EditConflict()
            draft = json.dumps(body.draft.model_dump(), ensure_ascii=False, separators=(",", ":"))
            if existing:
                row = conn.execute(text("""UPDATE product_workbench_edits
                    SET revision=revision+1, draft=CAST(:draft AS jsonb), updated_at=now()
                    WHERE product_id=:id AND revision=:revision
                    RETURNING revision, source_fingerprint, draft"""),
                    {"id": product_id, "revision": body.expectedRevision, "draft": draft}).mappings().first()
            else:
                row = conn.execute(text("""INSERT INTO product_workbench_edits
                    (product_id, revision, source_fingerprint, draft)
                    VALUES (:id, 1, :fingerprint, CAST(:draft AS jsonb))
                    ON CONFLICT (product_id) DO NOTHING RETURNING revision, source_fingerprint, draft"""),
                    {"id": product_id, "fingerprint": fingerprint, "draft": draft}).mappings().first()
            if row is None:
                raise EditConflict()
            return self._state(source, row)

    def create_manual(self, title: str, group_id) -> EditorState:
        product_id = f"manual:{uuid4().int}"
        with self.engine.begin() as conn:
            if group_id and not conn.execute(text("SELECT 1 FROM product_groups WHERE group_id=:id FOR SHARE"),
                                              {"id": group_id}).first():
                raise GroupNotFound()
            conn.execute(text("""INSERT INTO products(product_id, source_platform, source_product_id, title, group_id)
                VALUES (:id, 'manual', NULL, :title, :group_id)"""),
                {"id": product_id, "title": title, "group_id": group_id})
            source = self._source(conn, product_id)
            draft = ProductDraft(title=title)
            row = conn.execute(text("""INSERT INTO product_workbench_edits
                (product_id, revision, source_fingerprint, draft)
                VALUES (:id, 1, :fingerprint, CAST(:draft AS jsonb))
                RETURNING revision, source_fingerprint, draft"""),
                {"id": product_id, "fingerprint": source_fingerprint(source),
                 "draft": draft.model_dump_json()}).mappings().one()
            return self._state(source, row)
