"""Durable, individually revocable API credentials; product PostgreSQL is untouched."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from uuid import UUID, uuid4


PERMISSIONS = {
    "product.read": "查看商品和编辑所需的基本数据",
    "product.create": "新建商品",
    "product.update": "修改商品和读取编辑快照",
    "product.delete": "删除商品",
    "product.export": "导出商品数据包",
    "group.read": "查看分组",
    "group.create": "创建分组",
    "group.update": "修改分组名称",
    "group.delete": "删除分组",
    "group.assign": "调整商品分组",
    "image.upload": "上传图片",
    "precheck.read": "读取预检结果",
    "precheck.run": "发起预检",
    "category.read": "查询类目和属性规则",
    "central.read": "查看中控连接状态",
    "rpa.read": "通过 RPA 接口读取分组和数据包",
    "token.read": "查看自己发放的 Token",
    "token.create": "发放不超过自身权限的 Token",
    "token.update": "修改自己发放的 Token",
    "token.revoke": "撤销自己发放的 Token",
}
ALL_PERMISSIONS = frozenset(PERMISSIONS)
TOKEN_PATTERN = re.compile(r"^pdc_([0-9a-f]{32})_([A-Za-z0-9_-]{43})$")
MAX_DEPTH = 8


class TokenStoreUnavailable(Exception):
    pass


class TokenInvalid(Exception):
    pass


class TokenDenied(Exception):
    pass


class TokenNotFound(Exception):
    pass


class TokenInputError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    token_id: str | None
    permissions: frozenset[str]
    groups: frozenset[str] | None = None
    expires_at: int | None = None
    master: bool = False

    def has(self, permission: str) -> bool:
        return self.master or permission in self.permissions


MASTER = Principal(None, ALL_PERMISSIONS, master=True)
LEGACY_RPA = Principal(None, frozenset({"rpa.read"}))


def normalize_permissions(values: list[str]) -> frozenset[str]:
    if not isinstance(values, list) or not values or len(values) > len(PERMISSIONS) + 1:
        raise TokenInputError("请选择至少一项有效权限")
    if any(not isinstance(value, str) for value in values):
        raise TokenInputError("权限格式无效")
    result = set(values)
    if "*" in result:
        if len(result) != 1:
            raise TokenInputError("全部权限不能与其他权限混用")
        return ALL_PERMISSIONS
    if not result <= ALL_PERMISSIONS:
        raise TokenInputError("包含未知权限")
    return frozenset(result)


def normalize_groups(values: list[str] | None) -> frozenset[str] | None:
    if values is None:
        return None
    if not isinstance(values, list) or not values or len(values) > 200:
        raise TokenInputError("分组范围无效")
    normalized = set()
    for value in values:
        if value == "ungrouped":
            normalized.add(value)
            continue
        try:
            normalized.add(str(UUID(value)))
        except (ValueError, TypeError, AttributeError):
            raise TokenInputError("分组 ID 无效") from None
    return frozenset(normalized)


def normalize_expiry(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= int(time.time()):
        raise TokenInputError("有效期必须是未来时间")
    return value


def _validate_grant(actor: Principal, permissions, groups, expires_at):
    if not actor.master:
        if not permissions <= actor.permissions:
            raise TokenDenied("不能分配自己没有的权限")
        if actor.groups is not None and (groups is None or not groups <= actor.groups):
            raise TokenDenied("不能扩大分组范围")
        if actor.expires_at is not None and (expires_at is None or expires_at > actor.expires_at):
            raise TokenDenied("有效期不能超过发放者")


class TokenStore:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path is not None else None

    def _connect(self, *, create=False):
        if self.path is None or not self.path.parent.is_dir() or self.path.is_symlink():
            raise TokenStoreUnavailable()
        try:
            if create:
                try:
                    fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
                except FileExistsError:
                    pass
                else:
                    os.close(fd)
            if not self.path.is_file() or self.path.is_symlink():
                raise TokenStoreUnavailable()
            st = self.path.stat()
            if not stat.S_ISREG(st.st_mode) or (os.name != "nt" and (st.st_mode & 0o077)):
                raise TokenStoreUnavailable()
            db = sqlite3.connect(str(self.path), timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if create:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS scoped_tokens (
                        id TEXT PRIMARY KEY, token_hash BLOB NOT NULL,
                        name TEXT NOT NULL, permissions TEXT NOT NULL, groups_json TEXT,
                        parent_id TEXT REFERENCES scoped_tokens(id), expires_at INTEGER,
                        revoked_at INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS scoped_token_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT,
                        token_id TEXT NOT NULL, action TEXT NOT NULL, occurred_at INTEGER NOT NULL
                    );
                """)
                db.commit()
            return db
        except TokenStoreUnavailable:
            raise
        except (OSError, sqlite3.Error):
            raise TokenStoreUnavailable() from None

    @staticmethod
    def _principal(db, token_id: str) -> Principal:
        effective = None
        groups = None
        expiry = None
        current = token_id
        visited = set()
        now = int(time.time())
        while current is not None:
            if current in visited or len(visited) >= MAX_DEPTH:
                raise TokenInvalid()
            visited.add(current)
            row = db.execute("SELECT * FROM scoped_tokens WHERE id=?", (current,)).fetchone()
            if row is None or row["revoked_at"] is not None or (row["expires_at"] is not None and row["expires_at"] <= now):
                raise TokenInvalid()
            try:
                permitted = normalize_permissions(json.loads(row["permissions"]))
                allowed = normalize_groups(json.loads(row["groups_json"])) if row["groups_json"] is not None else None
            except (ValueError, TypeError, TokenInputError):
                raise TokenInvalid() from None
            effective = permitted if effective is None else effective & permitted
            if allowed is not None:
                groups = allowed if groups is None else groups & allowed
            if row["expires_at"] is not None:
                expiry = row["expires_at"] if expiry is None else min(expiry, row["expires_at"])
            current = row["parent_id"]
        return Principal(token_id, frozenset(effective or ()), groups, expiry)

    @staticmethod
    def _actor(db, actor: Principal, permission: str) -> Principal:
        actual = MASTER if actor.master else TokenStore._principal(db, actor.token_id)
        if not actual.has(permission):
            raise TokenDenied("没有 Token 管理权限")
        return actual

    @staticmethod
    def _record(row):
        return {"id": row["id"], "name": row["name"], "permissions": json.loads(row["permissions"]),
                "groupIds": json.loads(row["groups_json"]) if row["groups_json"] is not None else None,
                "expiresAt": row["expires_at"], "revokedAt": row["revoked_at"],
                "createdAt": row["created_at"], "updatedAt": row["updated_at"], "parentId": row["parent_id"]}

    @staticmethod
    def _target(db, actor: Principal, token_id: str):
        row = db.execute("SELECT * FROM scoped_tokens WHERE id=?", (token_id,)).fetchone()
        if row is None or (not actor.master and row["parent_id"] != actor.token_id):
            raise TokenNotFound()
        return row

    def authenticate(self, token: str) -> Principal:
        match = TOKEN_PATTERN.fullmatch(token)
        if not match:
            raise TokenInvalid()
        db = self._connect()
        try:
            row = db.execute("SELECT token_hash FROM scoped_tokens WHERE id=?", (match.group(1),)).fetchone()
            digest = hashlib.sha256(token.encode("ascii")).digest()
            if row is None or not hmac.compare_digest(row["token_hash"], digest):
                raise TokenInvalid()
            return self._principal(db, match.group(1))
        except sqlite3.Error:
            raise TokenStoreUnavailable() from None
        finally:
            db.close()

    def create(self, actor: Principal, name: str, permissions: list[str], groups: list[str] | None, expires_at: int | None):
        name = name.strip() if isinstance(name, str) else ""
        if not name or len(name) > 100:
            raise TokenInputError("Token 名称不能为空且不能超过 100 字")
        permissions = normalize_permissions(permissions)
        groups = normalize_groups(groups)
        expires_at = normalize_expiry(expires_at)
        db = self._connect(create=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            actor = self._actor(db, actor, "token.create")
            _validate_grant(actor, permissions, groups, expires_at)
            if not actor.master:
                current, depth = actor.token_id, 1
                while current:
                    row = db.execute("SELECT parent_id FROM scoped_tokens WHERE id=?", (current,)).fetchone()
                    current = row[0] if row else None
                    depth += 1
                if depth > MAX_DEPTH:
                    raise TokenDenied("Token 授权层级过深")
            token_id = uuid4().hex
            secret = "pdc_" + token_id + "_" + secrets.token_urlsafe(32)
            now = int(time.time())
            db.execute("""INSERT INTO scoped_tokens(id,token_hash,name,permissions,groups_json,parent_id,
                       expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                       (token_id, hashlib.sha256(secret.encode("ascii")).digest(), name,
                        json.dumps(sorted(permissions)), json.dumps(sorted(groups)) if groups is not None else None,
                        actor.token_id, expires_at, now, now))
            db.execute("INSERT INTO scoped_token_events(actor_id,token_id,action,occurred_at) VALUES (?,?,?,?)",
                       (actor.token_id, token_id, "create", now))
            record = self._record(db.execute("SELECT * FROM scoped_tokens WHERE id=?", (token_id,)).fetchone())
            db.commit()
            return record, secret
        except sqlite3.Error:
            db.rollback()
            raise TokenStoreUnavailable() from None
        finally:
            db.close()

    def list(self, actor: Principal):
        db = self._connect(create=actor.master)
        try:
            actor = self._actor(db, actor, "token.read")
            if actor.master:
                rows = db.execute("SELECT * FROM scoped_tokens ORDER BY created_at DESC, id").fetchall()
            else:
                rows = db.execute("SELECT * FROM scoped_tokens WHERE parent_id=? ORDER BY created_at DESC, id", (actor.token_id,)).fetchall()
            return [self._record(row) for row in rows]
        except sqlite3.Error:
            raise TokenStoreUnavailable() from None
        finally:
            db.close()

    def update(self, actor: Principal, token_id: str, changes: dict):
        if not changes or not set(changes) <= {"name", "permissions", "groupIds", "expiresAt"}:
            raise TokenInputError("没有有效的修改")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            actor = self._actor(db, actor, "token.update")
            row = self._target(db, actor, token_id)
            if row["revoked_at"] is not None:
                raise TokenDenied("已撤销的 Token 不能修改")
            name = changes.get("name", row["name"])
            name = name.strip() if isinstance(name, str) else ""
            if not name or len(name) > 100:
                raise TokenInputError("Token 名称不能为空且不能超过 100 字")
            permissions = normalize_permissions(changes.get("permissions", json.loads(row["permissions"])))
            groups = normalize_groups(changes.get("groupIds", json.loads(row["groups_json"]) if row["groups_json"] is not None else None))
            expires = normalize_expiry(changes.get("expiresAt", row["expires_at"]))
            _validate_grant(actor, permissions, groups, expires)
            if row["parent_id"] is not None:
                parent = self._principal(db, row["parent_id"])
                _validate_grant(parent, permissions, groups, expires)
            now = int(time.time())
            db.execute("UPDATE scoped_tokens SET name=?,permissions=?,groups_json=?,expires_at=?,updated_at=? WHERE id=?",
                       (name, json.dumps(sorted(permissions)), json.dumps(sorted(groups)) if groups is not None else None, expires, now, token_id))
            db.execute("INSERT INTO scoped_token_events(actor_id,token_id,action,occurred_at) VALUES (?,?,?,?)",
                       (actor.token_id, token_id, "update", now))
            result = self._record(db.execute("SELECT * FROM scoped_tokens WHERE id=?", (token_id,)).fetchone())
            db.commit()
            return result
        except sqlite3.Error:
            db.rollback()
            raise TokenStoreUnavailable() from None
        finally:
            db.close()

    def revoke(self, actor: Principal, token_id: str):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            actor = self._actor(db, actor, "token.revoke")
            self._target(db, actor, token_id)
            now = int(time.time())
            db.execute("UPDATE scoped_tokens SET revoked_at=COALESCE(revoked_at,?),updated_at=? WHERE id=?", (now, now, token_id))
            db.execute("INSERT INTO scoped_token_events(actor_id,token_id,action,occurred_at) VALUES (?,?,?,?)",
                       (actor.token_id, token_id, "revoke", now))
            db.commit()
        except sqlite3.Error:
            db.rollback()
            raise TokenStoreUnavailable() from None
        finally:
            db.close()
