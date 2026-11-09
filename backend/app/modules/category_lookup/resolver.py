"""Resolve a saved Douyin category ID path against the existing shop tree cache."""
from __future__ import annotations

import json
import re
import time
from threading import Lock

from fastapi import HTTPException

from app.modules.central.client import CentralApplicationClient
from .cache import CacheUnavailable, CategoryCache, merchant_cache_scope
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

    def cached(self, ids: list[str], shops) -> list[dict] | None:
        try:
            for shop in shops:
                if shop.session_version is None:
                    continue
                scope = merchant_cache_scope(shop.shop_id, shop.session_version)
                branches = {parent: self.cache.get("tree", scope, parent)
                            for parent in ["0", *ids[:-1]]}
                if levels := _walk(branches, ids):
                    return levels
            return None
        except CacheUnavailable:
            raise CategoryResolutionError() from None

    def resolve(self, ids: list[str]) -> list[dict]:
        if not ids or len(ids) > 4 or any(not re.fullmatch(r"[0-9]{1,20}", item) or not item.strip("0") for item in ids):
            raise CategoryResolutionError()
        from .api import _available
        try:
            shops = _available(self.central, self.lookup)
        except HTTPException:
            raise CategoryResolutionError() from None
        if levels := self.cached(ids, shops):
            return levels
        with _path_locks[hash(tuple(ids)) % len(_path_locks)]:
            # Waiting for another resolution may span a Session update or
            # authorization change; read current metadata again before use.
            try:
                shops = _available(self.central, self.lookup)
            except HTTPException:
                raise CategoryResolutionError() from None
            if levels := self.cached(ids, shops):
                return levels
            return self._fetch(ids, shops)

    def _fetch(self, ids: list[str], shops) -> list[dict]:
        # Imported lazily to avoid coupling the product service to API startup.
        from .api import MerchantIdentityUnverified, _limit, _session
        for shop in shops:
            try:
                with _limit(shop.shop_id):
                    session = _session(self.central, shop.shop_id, skip_unverified=True,
                                       version_hint=shop.session_version)
                    scope = merchant_cache_scope(session.shop_id, session.session_version)
                    allow_cache = shop.session_version == session.session_version
                    parent = "0"
                    levels = []
                    for identity in ids:
                        items = self.cache.get("tree", scope, parent) if allow_cache else None
                        item = _match(items, identity)
                        if item is None:
                            with _branch_locks[hash((scope, parent)) % len(_branch_locks)]:
                                items = self.cache.get("tree", scope, parent) if allow_cache else None
                                item = _match(items, identity)
                                if item is None:
                                    version = self.cache.tree_version(scope)
                                    probe = self.cache.get("tree_probe", scope, parent) if allow_cache else None
                                    recent = (isinstance(probe, dict) and probe.get("treeVersion") == version
                                              and isinstance(probe.get("checkedAt"), (int, float))
                                              and 0 <= time.time() - probe["checkedAt"] < _PROBE_TTL_SECONDS)
                                    if recent:
                                        break
                                    items = self.lookup.category_options(session, parent)
                                    self.cache.put("tree", scope, parent, items, tree_version=version)
                                    self.cache.put("tree_probe", scope, parent,
                                                   {"treeVersion": version, "checkedAt": time.time()},
                                                   tree_version=version)
                                    if self.cache.tree_version(scope) != version:
                                        raise CategoryResolutionError()
                                    item = _match(items, identity)
                        if item is None:
                            break
                        levels.append(item)
                        parent = identity
                    if len(levels) == len(ids):
                        return levels
            except MerchantIdentityUnverified:
                continue
            except LookupError as error:
                if error.reason == "platform_rejected" and error.platform_code == 10008:
                    continue
                raise CategoryResolutionError() from None
            except (CacheUnavailable, HTTPException):
                raise CategoryResolutionError() from None
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
