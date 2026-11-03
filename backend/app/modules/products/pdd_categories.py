"""Resolve PDD source-category IDs for display without changing source packages."""

from functools import lru_cache
from pathlib import Path
import re


_NUMERIC_PATH = re.compile(r"\d+(?:\s*(?:→|>|/)\s*\d+)*", re.ASCII)
_SEPARATOR = re.compile(r"\s*(?:→|>|/)\s*")


@lru_cache(maxsize=1)
def _categories() -> dict[str, tuple[str, str]]:
    result = {}
    try:
        with Path(__file__).with_name("pdd_categories.tsv").open(encoding="utf-8") as source:
            for line in source:
                identity, parent, name = line.rstrip("\n").split("\t", 2)
                result[identity] = (parent, name)
    except (OSError, ValueError):
        # A missing dictionary must not make the product library unavailable.
        return {}
    return result


def _complete_path(identity: str, categories: dict[str, tuple[str, str]]) -> list[tuple[str, str]]:
    result = []
    seen = set()
    while identity and identity != "0":
        if identity in seen or identity not in categories or len(result) >= 10:
            return []
        seen.add(identity)
        parent, name = categories[identity]
        result.append((identity, name))
        identity = parent
    return list(reversed(result))


def source_category_path(platform: str, path: str) -> str:
    """Display known PDD IDs as names; leave unknown and non-PDD data intact."""
    if platform not in {"pinduoduo", "pdd"} or not path or not _NUMERIC_PATH.fullmatch(path.strip()):
        return path
    identities = _SEPARATOR.split(path.strip())
    categories = _categories()
    complete = _complete_path(identities[-1], categories)
    if complete and [item[0] for item in complete][-len(identities):] == identities:
        return " → ".join(name for _, name in complete)
    return " → ".join(categories.get(identity, ("", identity))[1] for identity in identities)
