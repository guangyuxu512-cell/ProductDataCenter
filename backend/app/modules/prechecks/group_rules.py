"""Persist optional precheck grouping rules without changing the shared PG schema."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GroupRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    enabled: bool = True
    source: str
    passed: str
    incomplete: str

    @field_validator("source", "passed", "incomplete")
    @classmethod
    def valid_group(cls, value: str, info) -> str:
        permitted = {"all", "ungrouped"} if info.field_name == "source" else {"keep", "ungrouped"}
        if value in permitted:
            return value
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("分组选项无效") from None

    @model_validator(mode="after")
    def has_action(self):
        if self.enabled and self.passed == self.incomplete == "keep":
            raise ValueError("启用规则时请至少选择一个目标分组")
        return self


class GroupRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=0, ge=0)
    rules: list[GroupRule] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_rules(self):
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("规则标识重复")
        active = [rule.source for rule in self.rules if rule.enabled]
        if len(active) != len(set(active)):
            raise ValueError("同一来源分组只能启用一条规则")
        return self


class RulesUnavailable(Exception):
    pass


class RulesConflict(Exception):
    pass


class GroupRuleStore:
    def __init__(self, path: Path | None):
        self.path = path

    @contextmanager
    def snapshot(self) -> Iterator[GroupRules]:
        """Hold a read transaction while a completed check applies its rule."""
        if self.path is None:
            raise RulesUnavailable()
        if not self.path.exists():
            yield GroupRules()
            return
        db = None
        try:
            db = sqlite3.connect(str(self.path), timeout=10)
            db.execute("BEGIN")
            row = db.execute("SELECT version, payload FROM group_rules WHERE id=1").fetchone()
            config = GroupRules(version=row[0], rules=json.loads(row[1])) if row else GroupRules()
        except (sqlite3.Error, OSError, ValueError, TypeError):
            if db is not None:
                db.close()
            raise RulesUnavailable() from None
        try:
            yield config
        finally:
            db.close()

    def read(self) -> GroupRules:
        with self.snapshot() as config:
            return config

    def save(self, config: GroupRules) -> GroupRules:
        if self.path is None:
            raise RulesUnavailable()
        db = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            db = sqlite3.connect(str(self.path), timeout=10)
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS group_rules (id INTEGER PRIMARY KEY CHECK(id=1), "
                       "version INTEGER NOT NULL, payload TEXT NOT NULL)")
            row = db.execute("SELECT version FROM group_rules WHERE id=1").fetchone()
            current = row[0] if row else 0
            if config.version != current:
                raise RulesConflict()
            payload = json.dumps([rule.model_dump(mode="json") for rule in config.rules],
                                 ensure_ascii=False, separators=(",", ":"))
            db.execute("INSERT INTO group_rules(id,version,payload) VALUES(1,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload",
                       (current + 1, payload))
            db.commit()
            return GroupRules(version=current + 1, rules=config.rules)
        except RulesConflict:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise RulesUnavailable() from None
        finally:
            if db is not None:
                db.close()


def destination(config: GroupRules, current_group: str | None, status: str) -> str | None:
    """Only completed, determinate results may move; specific sources win."""
    if status not in {"ready", "needs_completion", "needs_category"}:
        return None
    source = current_group or "ungrouped"
    rules = [rule for rule in config.rules if rule.enabled]
    match = next((rule for rule in rules if rule.source == source), None)
    if match is None:
        match = next((rule for rule in rules if rule.source == "all"), None)
    if match is None:
        return None
    target = match.passed if status == "ready" else match.incomplete
    return None if target == "keep" or target == source else target
