import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.category_lookup import api
from app.modules.category_lookup.cache import CategoryCache, merchant_cache_scope
from app.modules.category_lookup.resolver import (
    CategoryResolutionError, CategoryResolver, category_ids, enrich_uu,
)


IDS = ["1000005069", "1000005072", "1000005114"]
NAMES = ["居家日用", "居家布艺", "靠垫/抱枕/午睡枕"]
BRANCHES = {parent: [{"id": identity, "name": name, "isLeaf": index == 2, "enabled": True}]
            for index, (parent, identity, name) in enumerate(zip(["0", *IDS], IDS, NAMES))}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, category_cache_file=tmp_path / "tree.sqlite3",
                        douyin_category_lookup_enabled=True)
    shop = SimpleNamespace(shop_id=uuid4(), session_version=1)
    monkeypatch.setattr(api, "_available", lambda central, lookup: [shop])
    monkeypatch.setattr(api, "_session", lambda central, shop_id, **kwargs:
                        SimpleNamespace(shop_id=shop_id, session_version=shop.session_version))
    monkeypatch.setattr(api, "_limit", lambda shop_id: nullcontext())
    calls = []

    class Lookup:
        def category_options(self, session, parent):
            calls.append(parent)
            return BRANCHES.get(parent, [])

    resolver = CategoryResolver(settings, central=object(), lookup=Lookup())
    return resolver, shop, calls


def test_cache_miss_fetches_exact_parents_then_reuses_persistent_cache(setup):
    resolver, shop, calls = setup
    expected = [{"id": identity, "name": name} for identity, name in zip(IDS, NAMES)]
    assert resolver.resolve(IDS) == expected
    assert calls == ["0", IDS[0], IDS[1]]
    calls.clear()
    assert resolver.resolve(IDS) == expected
    assert calls == []
    assert CategoryCache(resolver.settings.category_cache_file).get(
        "tree", merchant_cache_scope(shop.shop_id, 1), IDS[1]) == BRANCHES[IDS[1]]


def test_concurrent_requests_share_one_platform_lookup(setup):
    resolver, _, calls = setup
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: resolver.resolve(IDS), range(8)))
    assert all(value == values[0] for value in values)
    assert calls == ["0", IDS[0], IDS[1]]


def test_cached_branches_must_belong_to_same_shop(setup):
    resolver, shop, calls = setup
    cache = resolver.cache
    cache.put("tree", merchant_cache_scope(shop.shop_id, 1), "0", BRANCHES["0"])
    for parent in IDS[:2]:
        cache.put("tree", merchant_cache_scope(uuid4(), 1), parent, BRANCHES[parent])
    assert resolver.cached(IDS, [shop]) is None
    assert resolver.resolve(IDS)[-1]["name"] == NAMES[-1]
    assert calls == IDS[:2]


def test_missing_id_refreshes_old_branch_once_and_does_not_guess(setup):
    resolver, shop, calls = setup
    resolver.cache.put("tree", merchant_cache_scope(shop.shop_id, 1), "0", [])
    assert resolver.resolve(IDS)[-1]["name"] == NAMES[-1]
    assert calls == ["0", IDS[0], IDS[1]]
    missing = [IDS[0], IDS[1], "9999999999"]
    calls.clear()
    with pytest.raises(CategoryResolutionError):
        resolver.resolve(missing)
    # The parent was just refreshed and does not contain this ID.
    assert calls == []
    with pytest.raises(CategoryResolutionError):
        resolver.resolve(missing)
    assert calls == []


def test_manual_tree_refresh_clears_negative_probe(setup):
    resolver, shop, _ = setup
    resolver.resolve(IDS)
    cache, shop_id = resolver.cache, merchant_cache_scope(shop.shop_id, 1)
    assert cache.get("tree_probe", shop_id, "0") is not None
    cache.put("tree", shop_id, "0", BRANCHES["0"], refresh_tree=True)
    assert cache.get("tree_probe", shop_id, "0") is None


def test_session_version_change_requires_one_new_verified_resolution(setup):
    resolver, shop, calls = setup
    assert resolver.resolve(IDS)[-1]["name"] == NAMES[-1]
    assert calls == ["0", IDS[0], IDS[1]]
    calls.clear()
    assert resolver.resolve(IDS)[-1]["name"] == NAMES[-1]
    assert calls == []
    shop.session_version = 2
    assert resolver.resolve(IDS)[-1]["name"] == NAMES[-1]
    assert calls == ["0", IDS[0], IDS[1]]
    assert resolver.cache.get("tree", merchant_cache_scope(shop.shop_id, 1), "0") == BRANCHES["0"]
    assert resolver.cache.get("tree", merchant_cache_scope(shop.shop_id, 2), "0") == BRANCHES["0"]


def test_legacy_and_other_shop_cache_cannot_bypass_unavailable_verification(setup, monkeypatch):
    from fastapi import HTTPException

    resolver, shop, calls = setup
    other = uuid4()
    for parent in ["0", *IDS[:-1]]:
        resolver.cache.put("tree", str(shop.shop_id), parent, BRANCHES[parent])
        resolver.cache.put("tree", merchant_cache_scope(other, 1), parent, BRANCHES[parent])
    monkeypatch.setattr(api, "_session", lambda *args, **kwargs: (_ for _ in ()).throw(
        HTTPException(503, "身份验证暂不可用")))
    with pytest.raises(CategoryResolutionError):
        resolver.resolve(IDS)
    assert calls == []
    assert resolver.cache.get("tree", str(shop.shop_id), "0") == BRANCHES["0"]


@pytest.mark.parametrize("values", [
    {}, {"catId1": "0", "catId2": "2"}, {"catId1": "x"},
    {"catId1": True}, {"catId1": "1", "catId2": "0", "catId3": "3"},
])
def test_invalid_or_incomplete_id_paths_are_not_guessed(values):
    with pytest.raises(CategoryResolutionError):
        category_ids(values)


def test_enriched_uu_preserves_id_strings_and_rejects_metadata_collision(setup):
    resolver, _, _ = setup
    source = {"goodsInfo": {"catId1": IDS[0], "catId2": IDS[1], "catId3": IDS[2], "catId4": "0"},
              "goodsId": "3840809259533205534"}
    result = json.loads(enrich_uu(json.dumps(source).encode(), resolver))
    assert result["goodsInfo"] == source["goodsInfo"]
    assert result["_productDataCenterCategory"]["path"] == " → ".join(NAMES)
    assert [item["id"] for item in result["_productDataCenterCategory"]["levels"]] == IDS
    assert "_productDataCenterCategory" not in source
    source["_productDataCenterCategory"] = {"other": True}
    with pytest.raises(CategoryResolutionError):
        enrich_uu(json.dumps(source).encode(), resolver)


def test_batch_resolution_uses_saved_ids_and_keeps_other_platforms_separate(setup):
    from fastapi import Response
    from app.modules.products.schemas import ProductIds

    resolver, _, _ = setup
    lookup = resolver.lookup
    lookup.settings = resolver.settings
    rows = [
        {"product_id": "12345678", "source_platform": "douyin", **{f"cat{i}": value for i, value in enumerate([*IDS, "0"], 1)}},
        {"product_id": "23456789", "source_platform": "pinduoduo", **{f"cat{i}": value for i, value in enumerate([*IDS, "0"], 1)}},
    ]
    repository = SimpleNamespace(category_paths=lambda ids: rows)
    result = api.resolve_products(ProductIds(productIds=[row["product_id"] for row in rows]), Response(),
                                  object(), lookup, SimpleNamespace(repository=repository))
    assert result["items"][0]["path"] == " → ".join(NAMES)
    assert result["items"][0]["status"] == "resolved"
    assert result["items"][1]["status"] == "unsupported"
