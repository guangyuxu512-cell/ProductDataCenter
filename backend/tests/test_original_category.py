import pytest

from app.modules.products.repository import _original_category_id


@pytest.mark.parametrize(("levels", "expected"), [
    (("400", "300", "200", "100"), "400"),
    (("0", "300", "200", "100"), "300"),
    ((None, "", "0", "000"), None),
    (("bad", "300", "200", "100"), None),
    (("1" * 21, "300", "200", "100"), None),
    (("-1", "300", "200", "100"), None),
])
def test_original_category_uses_deepest_valid_source_id_without_guessing(levels, expected):
    assert _original_category_id(levels) == expected
