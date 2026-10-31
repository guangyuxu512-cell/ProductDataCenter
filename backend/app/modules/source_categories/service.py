"""Resolve approved PDD source categories without mutating product data."""

import re
from dataclasses import dataclass
from pathlib import Path
from secrets import compare_digest

from app.core.exceptions.errors import AppError
from app.modules.source_categories.pdd import (
    InvalidCategoryDictionary,
    SourceCategory,
    read_dictionary,
    valid_category_id,
)


class CategoryNotFound(AppError):
    code = "SOURCE_CATEGORY_NOT_FOUND"
    message = "当前来源类目表中未找到该类目"
    status_code = 404


class DictionaryUnavailable(AppError):
    code = "PDD_CATEGORY_DICTIONARY_UNAVAILABLE"
    message = "拼多多来源类目表尚未就绪"
    status_code = 503


@dataclass(frozen=True, slots=True)
class ResolvedSourceCategory:
    category: SourceCategory
    path: tuple[SourceCategory, ...]
    dictionary_sha256: str


class PddSourceCategoryService:
    def __init__(self, path: Path | None, expected_sha256: str | None) -> None:
        self.path = path
        self.expected_sha256 = expected_sha256

    def get(self, category_id: str) -> ResolvedSourceCategory:
        if not valid_category_id(category_id):
            raise CategoryNotFound()
        if (self.path is None or self.expected_sha256 is None
                or re.fullmatch(r"[0-9a-f]{64}", self.expected_sha256) is None):
            raise DictionaryUnavailable()
        try:
            dictionary = read_dictionary(self.path)
        except (OSError, InvalidCategoryDictionary):
            raise DictionaryUnavailable() from None
        if not compare_digest(dictionary.sha256, self.expected_sha256):
            raise DictionaryUnavailable()
        category = dictionary.get(category_id)
        if category is None:
            raise CategoryNotFound()
        return ResolvedSourceCategory(
            category=category,
            path=tuple(dictionary.categories[item] for item in category.path_ids),
            dictionary_sha256=dictionary.sha256,
        )
