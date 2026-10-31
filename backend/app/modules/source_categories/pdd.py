"""Read a versioned PDD source-category dictionary without changing products."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Mapping


MAX_CSV_BYTES = 32 * 1024 * 1024
MAX_CATEGORIES = 200_000
MAX_DEPTH = 16
_ID = re.compile(r"[1-9][0-9]{0,31}\Z", re.ASCII)
_REQUIRED_COLUMNS = {
    "id", "name", "parent_id", "level", "is_leaf", "path_ids", "path_names",
    "is_hidden", "is_deleted",
}
_LOAD_LOCK = Lock()


class InvalidCategoryDictionary(ValueError):
    """The dictionary could not be safely interpreted as a complete source tree."""


@dataclass(frozen=True, slots=True)
class SourceCategory:
    category_id: str
    name: str
    parent_id: str
    path_ids: tuple[str, ...]
    path_names: tuple[str, ...]
    is_leaf: bool
    is_hidden: bool
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class PddCategoryDictionary:
    sha256: str
    categories: Mapping[str, SourceCategory]

    def get(self, category_id: str) -> SourceCategory | None:
        return self.categories.get(category_id)


def valid_category_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


def _flag(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise InvalidCategoryDictionary("invalid category flag")


def parse_dictionary(content: bytes) -> PddCategoryDictionary:
    if not content or len(content) > MAX_CSV_BYTES:
        raise InvalidCategoryDictionary("invalid dictionary size")
    categories: dict[str, SourceCategory] = {}
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        if not reader.fieldnames or not _REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise InvalidCategoryDictionary("missing dictionary columns")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise InvalidCategoryDictionary("duplicate dictionary columns")
        for row in reader:
            if len(categories) >= MAX_CATEGORIES or None in row:
                raise InvalidCategoryDictionary("invalid dictionary rows")
            category_id = row["id"].strip()
            name = row["name"].strip()
            parent_id = row["parent_id"].strip()
            path_ids = tuple(item.strip() for item in row["path_ids"].split(" > "))
            path_names = tuple(item.strip() for item in row["path_names"].split(" > "))
            level = row["level"].strip()
            if (
                not valid_category_id(category_id) or category_id in categories or not name
                or not level.isascii() or not level.isdigit() or not 1 <= int(level) <= MAX_DEPTH
                or len(path_ids) != int(level) or len(path_ids) != len(path_names)
                or not all(valid_category_id(item) for item in path_ids)
                or not all(path_names) or len(set(path_ids)) != len(path_ids)
                or path_ids[-1] != category_id or path_names[-1] != name
                or parent_id != (path_ids[-2] if len(path_ids) > 1 else "0")
            ):
                raise InvalidCategoryDictionary("inconsistent category row")
            categories[category_id] = SourceCategory(
                category_id=category_id, name=name, parent_id=parent_id,
                path_ids=path_ids, path_names=path_names,
                is_leaf=_flag(row["is_leaf"]), is_hidden=_flag(row["is_hidden"]),
                is_deleted=_flag(row["is_deleted"]),
            )
    except (UnicodeDecodeError, csv.Error, AttributeError, TypeError, KeyError, ValueError) as error:
        if isinstance(error, InvalidCategoryDictionary):
            raise
        raise InvalidCategoryDictionary("invalid dictionary format") from None
    if not categories:
        raise InvalidCategoryDictionary("empty dictionary")
    parents = {category.parent_id for category in categories.values() if category.parent_id != "0"}
    for category in categories.values():
        if category.is_leaf == (category.category_id in parents):
            raise InvalidCategoryDictionary("inconsistent leaf state")
        for index, ancestor_id in enumerate(category.path_ids):
            ancestor = categories.get(ancestor_id)
            if (
                ancestor is None or ancestor.name != category.path_names[index]
                or ancestor.path_ids != category.path_ids[:index + 1]
                or ancestor.path_names != category.path_names[:index + 1]
            ):
                raise InvalidCategoryDictionary("incomplete category tree")
    return PddCategoryDictionary(
        sha256=hashlib.sha256(content).hexdigest(),
        categories=MappingProxyType(categories),
    )


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@lru_cache(maxsize=2)
def _read_cached(path: Path, identity: tuple[int, int, int, int, int]) -> PddCategoryDictionary:
    if identity[2] <= 0 or identity[2] > MAX_CSV_BYTES:
        raise InvalidCategoryDictionary("invalid dictionary size")
    with path.open("rb") as stream:
        if _identity(os.fstat(stream.fileno())) != identity:
            raise InvalidCategoryDictionary("dictionary changed while reading")
        content = stream.read(MAX_CSV_BYTES + 1)
        if _identity(os.fstat(stream.fileno())) != identity or _identity(path.stat()) != identity:
            raise InvalidCategoryDictionary("dictionary changed while reading")
    return parse_dictionary(content)


def read_dictionary(path: Path) -> PddCategoryDictionary:
    """Load one copy per file version, including concurrent cold requests."""
    # functools.lru_cache can execute the same missing key on multiple threads.
    # The second lookup under this lock reuses a completed version instead.
    with _LOAD_LOCK:
        return _read_cached(path, _identity(path.stat()))
