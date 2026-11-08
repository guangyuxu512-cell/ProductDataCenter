"""Resolve a saved Douyin category ID path against the existing shop tree cache."""
from __future__ import annotations

import json
import re
import time
from threading import Lock

from fastapi import HTTPException

from app.modules.central.client import CentralApplicationClient
from .cache import CacheUnavailable, CategoryCache
from .client import DouyinCategoryClient, LookupError


class CategoryResolutionError(Exception):
    """A complete, verified category path could not be obtained."""


_path_locks = [Lock() for _ in range(128)]
_branch_locks = [Lock() for _ in range(128)]
_PROBE_TTL_SECONDS = 60
_METADATA_KEY = "_productDataCenterCategory"


def category_ids(goods: object) -> list[str]:
    if not isinstance(goods, dict):
        raise CategoryResolutionError()
    result = []
    ended = False
    for index in range(1, 5):
        value = goods.get(f"catId{index}")
        if value in (None, "", "0", 0) and not isinstance(value, bool):
            ended = True
            continue
        if (ended or isinstance(value, bool) or not isinstance(value, (str, int))
                or not re.fullmatch(r"[0-9]{1,20}", str(value)) or not str(value).strip("0")):
            raise CategoryResolutionError()
        result.append(str(value))
    if not result:
        raise CategoryResolutionError()
    return result


def _match(items: object, identity: str) -> dict | None:
    if not isinstance(items, list):
        return None
    matches = [item for item in items if isinstance(item, dict) and str(item.get("id")) == identity]
    if len(matches) != 1:
        return None
    name = matches[0].get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 300 or name.strip().isdecimal():
        return None
    return {"id": identity, "name": name.strip()}


def _walk(branches: dict[str, list], ids: list[str]) -> list[dict] | None:
    parent = "0"
    levels = []
    for identity in ids:
        item = _match(branches.get(parent), identity)
        if item is None:
            return None
        levels.append(item)
        parent = identity
    return levels


class CategoryResolver:
    def __init__(self, settings, *, central=None, lookup=None):
        self.settings = settings
        self.cache = CategoryCache(settings.category_cache_file)
        self.central = central or CentralApplicationClient(settings)
        self.lookup = lookup or DouyinCategoryClient(settings)

    def cached(self, ids: list[str]) -> list[dict] | None:
        try:
            branches = self.cache.tree_branches(["0", *ids[:-1]])
            for shop in sorted(branches):
                if levels := _walk(branches[shop], ids):
                    return levels
            return None
        except CacheUnavailable:
            raise CategoryResolutionError() from None

    def resolve(self, ids: list[str]) -> list[dict]:
        if not ids or len(ids) > 4 or any(not re.fullmatch(r"[0-9]{1,20}", item) or not item.strip("0") for item in ids):
            raise CategoryResolutionError()
        if levels := self.cached(ids):
            return levels
        with _path_locks[hash(tuple(ids)) % len(_path_locks)]:
            if levels := self.cached(ids):
                return levels
            return self._fetch(ids)

    def _fetch(self, ids: list[str]) -> list[dict]:
        # Imported lazily to avoid coupling the product service to API startup.
        from .api import _available, _limit, _session

        try:
            shops = _available(self.central, self.lookup)
        except HTTPException:
            raise CategoryResolutionError() from None
        for shop in shops:
            shop_id = str(shop.shop_id)
            session = None
            parent = "0"
            levels = []
            try:
                for identity in ids:
                    items = self.cache.get("tree", shop_id, parent)
                    item = _match(items, identity)
                    if item is None:
                        with _branch_locks[hash((shop_id, parent)) % len(_branch_locks)]:
                            items = self.cache.get("tree", shop_id, parent)
                            item = _match(items, identity)
                            if item is None:
                                version = self.cache.tree_version()
                                probe = self.cache.get("tree_probe", shop_id, parent)
                                recent = (isinstance(probe, dict) and probe.get("treeVersion") == version
                                          and isinstance(probe.get("checkedAt"), (int, float))
                                          and 0 <= time.time() - probe["checkedAt"] < _PROBE_TTL_SECONDS)
                                if recent:
                                    break
                                if session is None:
                                    session = _session(self.central, shop.shop_id)
                                with _limit(shop.shop_id):
                                    items = self.lookup.category_options(session, parent)
                                self.cache.put("tree", shop_id, parent, items, tree_version=version)
                                self.cache.put("tree_probe", shop_id, parent,
                                               {"treeVersion": version, "checkedAt": time.time()})
                                if self.cache.tree_version() != version:
                                    raise CategoryResolutionError()
                                item = _match(items, identity)
                    if item is None:
                        break
                    levels.append(item)
                    parent = identity
                if len(levels) == len(ids):
                    return levels
            except (CacheUnavailable, HTTPException, LookupError):
                continue
        raise CategoryResolutionError()


def category_metadata(levels: list[dict]) -> dict:
    return {"platform": "douyin", "levels": levels, "path": " → ".join(item["name"] for item in levels)}


def enrich_uu(content: bytes, resolver: CategoryResolver) -> bytes:
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise CategoryResolutionError()
        levels = resolver.resolve(category_ids(payload.get("goodsInfo")))
        metadata = category_metadata(levels)
        if _METADATA_KEY in payload and payload[_METADATA_KEY] != metadata:
            raise CategoryResolutionError()
        payload[_METADATA_KEY] = metadata
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise CategoryResolutionError() from None
