from app.core.config import Settings
from app.modules.category_lookup.cache import CategoryCache
from app.modules.category_lookup.resolver import CategoryResolver
from app.modules.products.schemas import ProductEdit
from app.modules.products.service import ProductService


LEVELS = [{"id": "1000009092", "name": "餐饮厨具"}, {"id": "1000009147", "name": "砧板/菜板"}]


def test_collector_target_requires_complete_cached_shop_tree(tmp_path):
    settings = Settings(category_cache_file=tmp_path / "categories.sqlite")
    cache = CategoryCache(settings.category_cache_file)
    cache.put("tree", "shop", "0", [{**LEVELS[0], "isLeaf": False}])
    cache.put("tree", "shop", LEVELS[0]["id"], [{**LEVELS[1], "isLeaf": True}])
    resolver = CategoryResolver(settings)
    assert resolver.cached_confirmed_leaf(LEVELS)
    assert not resolver.cached_confirmed_leaf(LEVELS[:1])
    assert not resolver.cached_confirmed_leaf([LEVELS[0], {**LEVELS[1], "name": "不同名称"}])
    assert not resolver.cached_confirmed_leaf([{"id": "50003449", "name": "砧板/菜板"}])
    separate = Settings(category_cache_file=tmp_path / "separate-shops.sqlite")
    separate_cache = CategoryCache(separate.category_cache_file)
    separate_cache.put("tree", "one", "0", [{**LEVELS[0], "isLeaf": False}])
    separate_cache.put("tree", "two", LEVELS[0]["id"], [{**LEVELS[1], "isLeaf": True}])
    assert not CategoryResolver(separate).cached_confirmed_leaf(LEVELS)
    assert not CategoryResolver(Settings(category_cache_file=None)).cached_confirmed_leaf(LEVELS)

    class Repository:
        def create_manual(self, *args, **kwargs):
            self.values = kwargs
            return "manual:12345678"

    repository = Repository()
    service = ProductService(repository, settings)
    edit = ProductEdit(expectedVersion="0" * 64, title="商品", category=LEVELS)
    assert service.create_manual("商品", "a" * 32, edit, source_platform="jushuitan",
                                 source_product_id="资料编码-中文")["productId"] == "manual:12345678"
    assert repository.values["verified_douyin_target"] == LEVELS
    assert repository.values["source_product_id"] == "资料编码-中文"
    unmatched = edit.model_copy(update={"category": edit.category[:1]})
    service.create_manual("商品", "a" * 32, unmatched, source_platform="jushuitan")
    assert "verified_douyin_target" not in repository.values
