"""One-time, exact-origin migration of owned product image URLs in PostgreSQL.

Defaults to a rolled-back dry run. The database URL can be supplied on stdin
so maintenance credentials do not appear in command lines or logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

from .urls import canonical_image_values, canonical_product_image_url


def _origin(value: str, *, https_only: bool = False) -> str:
    value = value.strip().rstrip("/")
    p = urlsplit(value)
    try:
        _ = p.port
    except ValueError:
        raise ValueError("invalid image origin") from None
    if (p.scheme not in ({"https"} if https_only else {"http", "https"}) or not p.hostname
            or p.username is not None or p.password is not None or p.path or p.query or p.fragment
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ValueError("invalid image origin")
    return value


def migrate(engine, public_base: str, legacy_bases: list[str], *, apply: bool = False) -> dict:
    public = _origin(public_base, https_only=True)
    old = [_origin(item) for item in legacy_bases]
    if not old or public in old or len(set(old)) != len(old):
        raise ValueError("invalid legacy image origins")
    legacy = ",".join(old)
    summary = {"products": 0, "image_rows": 0, "sku_rows": 0, "applied": apply}
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            if apply:
                # Product and projection updates are committed together and
                # concurrent collection/edit writes cannot reintroduce old URLs.
                conn.execute(text("LOCK TABLE products, product_images, product_skus IN SHARE ROW EXCLUSIVE MODE"))
            rows = conn.execute(text("SELECT product_id, uu_json::text AS package FROM products "
                                     "WHERE uu_json::text LIKE '%/rpa/v1/product-images/%'")).mappings().all()
            for row in rows:
                original = json.loads(row["package"])
                updated = canonical_image_values(original, public, legacy)
                if updated == original:
                    continue
                summary["products"] += 1
                if apply:
                    saved = conn.execute(text("UPDATE products SET uu_json=CAST(:package AS jsonb) "
                                              "WHERE product_id=:id RETURNING uu_json::text"),
                                         {"id": row["product_id"], "package": json.dumps(updated, ensure_ascii=False)}).scalar_one()
                    conn.execute(text("UPDATE products SET uu_sha256=:sha WHERE product_id=:id"),
                                 {"id": row["product_id"], "sha": hashlib.sha256(saved.encode("utf-8")).hexdigest()})
            images = conn.execute(text("SELECT product_id,image_type,sort_order,source_url,rel_path "
                                       "FROM product_images WHERE source_url LIKE '%/rpa/v1/product-images/%' "
                                       "OR rel_path LIKE '%/rpa/v1/product-images/%'")).mappings().all()
            for row in images:
                source = canonical_product_image_url(row["source_url"], public, legacy)
                path = canonical_product_image_url(row["rel_path"], public, legacy)
                if source == row["source_url"] and path == row["rel_path"]:
                    continue
                summary["image_rows"] += 1
                if apply:
                    conn.execute(text("UPDATE product_images SET source_url=:source,rel_path=:path "
                                      "WHERE product_id=:id AND image_type=:kind AND sort_order=:position"),
                                 {"source": source, "path": path, "id": row["product_id"],
                                  "kind": row["image_type"], "position": row["sort_order"]})
            skus = conn.execute(text("SELECT product_id,sku_id,image_rel_path FROM product_skus "
                                     "WHERE image_rel_path LIKE '%/rpa/v1/product-images/%'")).mappings().all()
            for row in skus:
                path = canonical_product_image_url(row["image_rel_path"], public, legacy)
                if path == row["image_rel_path"]:
                    continue
                summary["sku_rows"] += 1
                if apply:
                    conn.execute(text("UPDATE product_skus SET image_rel_path=:path "
                                      "WHERE product_id=:id AND sku_id=:sku"),
                                 {"path": path, "id": row["product_id"], "sku": row["sku_id"]})
            tx.commit() if apply else tx.rollback()
        except BaseException:
            tx.rollback()
            raise
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--old-origin", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-url-stdin", action="store_true")
    args = parser.parse_args()
    if args.database_url_stdin:
        database_url = sys.stdin.readline().strip()
    else:
        from app.core.config import get_settings
        database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("Database connection is unavailable")
    engine = create_engine(database_url)
    try:
        print(json.dumps(migrate(engine, args.public_origin, args.old_origin, apply=args.apply), ensure_ascii=False))
    except Exception as error:
        # Avoid printing connection URLs or database contents.
        raise SystemExit("Image URL migration failed: " + type(error).__name__) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
