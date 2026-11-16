import json

import pytest
from pydantic import ValidationError

from app.modules.products.errors import ExportUnavailable, ProductRequestError
from app.modules.products.export import current_uu_bytes
from app.modules.products.manual import manual_package
from app.modules.products.queries import build_product_list_queries, parse_product_list_options
from app.modules.products.schemas import ManualProductCreate, ProductSourceIdentityUpdate


def test_create_source_identity_preserves_long_string_and_platform():
    item = ManualProductCreate(title="测试商品", sourceProductId=" 9876543210123456789 ")
    assert item.sourceProductId == "9876543210123456789" and item.sourcePlatform == "douyin"
    assert ManualProductCreate(title="商品", sourcePlatform="jushuitan").sourceProductId is None
    for value in (9876543210123456789, "", "  ", "a\x00b", "x" * 129):
        with pytest.raises(ValidationError):
            ManualProductCreate(title="商品", sourceProductId=value)
    with pytest.raises(ValidationError):
        ProductSourceIdentityUpdate()
    with pytest.raises(ValidationError):
        ManualProductCreate(title="商品", sourcePlatform="unknown")


def test_exact_source_lookup_is_parameterized_and_platform_scoped():
    options = parse_product_list_options({"sourceProductId": " SKU-A.12 ", "platform": "jushuitan"})
    query, count = build_product_list_queries(options)
    assert "p.source_product_id = $1" in query.sql
    assert "p.source_platform = $2" in query.sql
    assert query.params[:2] == ["SKU-A.12", "jushuitan"]
    assert count is not None and count.params == ["SKU-A.12", "jushuitan"]
    with pytest.raises(ProductRequestError):
        parse_product_list_options({"sourceProductId": "a\x00b"})


def test_manual_package_and_legacy_export_use_confirmed_source_id_without_guessing():
    source = "9876543210123456789"
    package, _ = manual_package("商品", source_id=source)
    assert package["goodsId"] == source
    old, _ = manual_package("商品")
    text = json.dumps(old, ensure_ascii=False)
    row = {"product_id": "manual:12345678", "source_platform": "douyin",
           "source_product_id": source, "uu_text": text}
    result, origin = current_uu_bytes(row, 100_000)
    assert origin == "database" and json.loads(result)["goodsId"] == source
    assert "goodsId" not in json.loads(text)
    conflicting = {**row, "uu_text": json.dumps({**old, "goodsId": "different"})}
    with pytest.raises(ExportUnavailable, match="来源 ID"):
        current_uu_bytes(conflicting, 100_000)
    jst = {**row, "source_platform": "jushuitan"}
    assert json.loads(current_uu_bytes(jst, 100_000)[0]).get("goodsId") is None
