"""Persistent category definitions only; never store cookies or product values."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID


class CacheUnavailable(Exception):
    pass


SCHEMA_FORMAT_VERSION = 3


def merchant_cache_scope(shop_id: UUID, session_version: int) -> str:
    """A versioned namespace never collides with unverified historical rows."""
    if (not isinstance(shop_id, UUID) or isinstance(session_version, bool)
            or not isinstance(session_version, int) or session_version <= 0):
        raise CacheUnavailable()
    return f"merchant-v1:{shop_id}:{session_version}"


class CategoryCache:
    def __init__(self, path: Path | None):
        self.path = path

    def _connect(self):
        if self.path is None:
            raise CacheUnavailable()
        db = None
        try:
            db = sqlite3.connect(str(self.path), timeout=10)
            db.execute("""CREATE TABLE IF NOT EXISTS category_cache (
                kind TEXT NOT NULL, shop_id TEXT NOT NULL, cache_key TEXT NOT NULL,
                payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(kind, shop_id, cache_key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS category_cache_meta (
                name TEXT PRIMARY KEY, version INTEGER NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO category_cache_meta(name, version) VALUES ('tree', 0)")
            db.commit()
            return db
        except (sqlite3.Error, OSError):
            if db is not None:
                db.close()
            raise CacheUnavailable() from None

    @contextmanager
    def _transaction(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, kind: str, shop_id: str, key: str):
        try:
            with self._transaction() as db:
                row = db.execute("SELECT payload FROM category_cache WHERE kind=? AND shop_id=? AND cache_key=?",
                                 (kind, shop_id, key)).fetchone()
            value = json.loads(row[0]) if row else None
            if kind != "schema" or value is None:
                return value
            # Version-one rows are plain normalized lists and have already
            # discarded the platform control metadata.  Treat each such row
            # as one cache miss; the successful live response below replaces
            # it with the versioned representation and normal caching resumes.
            if (not isinstance(value, dict) or value.get("formatVersion") != SCHEMA_FORMAT_VERSION
                    or not isinstance(value.get("attributes"), list)):
                return None
            return value["attributes"]
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise CacheUnavailable() from None

    def tree_version(self, shop_id: str) -> int:
        try:
            with self._transaction() as db:
                name = "tree:" + shop_id
                db.execute("INSERT OR IGNORE INTO category_cache_meta(name, version) VALUES (?, 0)", (name,))
                return int(db.execute("SELECT version FROM category_cache_meta WHERE name=?", (name,)).fetchone()[0])
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise CacheUnavailable() from None

    def schema_version(self, shop_id: str, key: str) -> int:
        try:
            with self._transaction() as db:
                name = "schema:" + shop_id + ":" + key
                db.execute("INSERT OR IGNORE INTO category_cache_meta(name, version) VALUES (?, 0)", (name,))
                return int(db.execute("SELECT version FROM category_cache_meta WHERE name=?", (name,)).fetchone()[0])
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise CacheUnavailable() from None

    def put(self, kind: str, shop_id: str, key: str, value, *,
            tree_version: int | None = None, refresh_tree: bool = False,
            refresh_schema: bool = False, schema_version: int | None = None) -> None:
        try:
            stored = ({"formatVersion": SCHEMA_FORMAT_VERSION, "attributes": value}
                      if kind == "schema" else value)
            payload = json.dumps(stored, ensure_ascii=False, separators=(",", ":"))
            with self._transaction() as db:
                db.execute("BEGIN IMMEDIATE")
                tree_name = "tree:" + shop_id
                schema_name = "schema:" + shop_id + ":" + key
                if refresh_tree:
                    db.execute("INSERT OR IGNORE INTO category_cache_meta(name, version) VALUES (?, 0)", (tree_name,))
                    current = int(db.execute("SELECT version FROM category_cache_meta WHERE name=?", (tree_name,)).fetchone()[0])
                    if tree_version is not None and current != tree_version:
                        return
                    db.execute("UPDATE category_cache_meta SET version=version+1 WHERE name=?", (tree_name,))
                    db.execute("DELETE FROM category_cache WHERE shop_id=? AND kind IN ('tree', 'tree_probe')", (shop_id,))
                elif kind in {'tree', 'tree_probe'} and tree_version is not None:
                    row = db.execute("SELECT version FROM category_cache_meta WHERE name=?", (tree_name,)).fetchone()
                    if row is None:
                        return
                    current = int(row[0])
                    if current != tree_version:
                        return
                if refresh_schema:
                    db.execute("INSERT OR IGNORE INTO category_cache_meta(name, version) VALUES (?, 0)", (schema_name,))
                    current = int(db.execute("SELECT version FROM category_cache_meta WHERE name=?", (schema_name,)).fetchone()[0])
                    if schema_version is not None and current != schema_version:
                        return
                    db.execute("UPDATE category_cache_meta SET version=version+1 WHERE name=?", (schema_name,))
                    db.execute("DELETE FROM category_cache WHERE kind='schema' AND shop_id=? AND cache_key=?", (shop_id, key))
                elif kind == 'schema' and schema_version is not None:
                    row = db.execute("SELECT version FROM category_cache_meta WHERE name=?", (schema_name,)).fetchone()
                    if row is None or int(row[0]) != schema_version:
                        return
                db.execute("""INSERT INTO category_cache(kind,shop_id,cache_key,payload) VALUES (?,?,?,?)
                    ON CONFLICT(kind,shop_id,cache_key) DO UPDATE SET
                    payload=excluded.payload, updated_at=CURRENT_TIMESTAMP""", (kind, shop_id, key, payload))
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise CacheUnavailable() from None
