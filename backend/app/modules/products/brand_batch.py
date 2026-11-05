"""Explicit one-time no-brand update; never runs during an ordinary read."""

from __future__ import annotations

import argparse
import json

from fastapi import Response
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.modules.category_lookup.api import AutoSchemaBody, schema_auto
from app.modules.category_lookup.client import DouyinCategoryClient
from app.modules.central.client import CentralApplicationClient
from .brand_defaults import no_brand_selection
from .repository import ProductRepository


def run(*, apply: bool, limit: int | None = None) -> dict:
    settings = get_settings()
    engine = get_database_engine()
    repository = ProductRepository(engine)
    central = CentralApplicationClient(settings)
    lookup = DouyinCategoryClient(settings)
    sql = """SELECT product_id FROM products WHERE uu_json IS NOT NULL
        AND source_platform IN ('douyin','pinduoduo','pdd') ORDER BY product_id"""
    if limit is not None:
        sql += " LIMIT :limit"
    with engine.connect().execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True) as conn, conn.begin():
        product_ids = list(conn.execute(text(sql), {"limit": limit} if limit is not None else {}).scalars())
    schemas: dict[str, object | None] = {}
    counts = {"scanned": 0, "matchable": 0, "updated": 0, "already": 0, "manual": 0,
              "unmatched": 0, "unsupported": 0, "missing": 0, "failed": 0}
    unresolved = []
    for product_id in product_ids:
        counts["scanned"] += 1
        try:
            detail = repository.detail(product_id)
            if not detail:
                counts["missing"] += 1
                unresolved.append({"productId": product_id, "reason": "missing"})
                continue
            platform = detail["product"]["source_platform"]
            category_id = (detail.get("sourceCategoryId") if platform == "douyin" else
                           detail["targetCategory"][-1]["id"] if detail.get("targetCategory") else None)
            if not category_id:
                counts["unmatched"] += 1
                unresolved.append({"productId": product_id, "reason": "category_missing"})
                continue
            if category_id not in schemas:
                schema = schema_auto(AutoSchemaBody(categoryId=category_id,
                    title=detail["product"].get("title") or "商品"), Response(), central, lookup)
                schemas[category_id] = no_brand_selection(schema.attributes)
            selection = schemas[category_id]
            if not selection:
                counts["unmatched"] += 1
                unresolved.append({"productId": product_id, "reason": "no_brand_option_missing"})
                continue
            if not apply:
                counts["matchable"] += 1
                continue
            outcome = repository.set_default_brand(product_id, selection, force=True, mark_modified=False)
            if outcome not in counts:
                outcome = "failed"
            counts[outcome] += 1
            if outcome not in {"updated", "already"}:
                unresolved.append({"productId": product_id, "reason": outcome})
        except Exception:
            counts["failed"] += 1
            unresolved.append({"productId": product_id, "reason": "processing_failed"})
    return {"mode": "apply" if apply else "dry-run", "counts": counts,
            "unresolved": unresolved, "categoryCount": len(schemas)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and not 1 <= args.limit <= 1_000_000:
        parser.error("--limit must be between 1 and 1000000")
    print(json.dumps(run(apply=args.apply, limit=args.limit), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
