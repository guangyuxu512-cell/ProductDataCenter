from app.modules.products.pdd_categories import source_category_path


def test_pdd_path_resolves_the_uploaded_category_dictionary():
    assert source_category_path("pinduoduo", "9323 → 9481 → 10417 → 11366") == (
        "五金工具 → 手动工具 → 扳手 → 梅花扳手"
    )
    assert source_category_path("pinduoduo", "11366") == "五金工具 → 手动工具 → 扳手 → 梅花扳手"


def test_unknown_ids_and_non_pdd_categories_are_not_invented():
    assert source_category_path("pinduoduo", "9323 > 999999999") == "五金工具 → 999999999"
    assert source_category_path("pinduoduo", "家居/厨房") == "家居/厨房"
    assert source_category_path("douyin", "9323 → 9481") == "9323 → 9481"
