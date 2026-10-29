from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess

import pytest

from app.modules.products.errors import ProductRequestError
from app.modules.products.queries import build_product_list_queries, parse_product_list_options

CASES = [
    {}, {"q": "厨房收纳"}, {"q": "收纳"}, {"q": "收%纳_"}, {"q": "x' OR 1=1 --"},
    {"productId": "3760269504500859111"}, {"productId": "PDD:3760269504500859111", "q": "ignored"},
    {"platform": "DOUYIN"}, {"platform": "pinduoduo", "groupId": "ungrouped"},
    {"groupId": "00000000-0000-4000-8000-000000000001"},
    {"capturedFrom": "2026-10-26", "capturedTo": "2026-10-26"},
    {"capturedFromTime": "2026-10-26T08:18:34", "capturedToTime": "2026-10-26T08:18:34"},
    {"capturedFromTime": "2026-10-26T08:18", "capturedTo": "2026-10-26"},
    {"capturedFromTime": "2026-10-26T09:00:00", "capturedFrom": "2026-10-25", "capturedToTime": "2026-10-27T00:00:00"},
    {"limit": "20", "offset": "299800", "includeTotal": "false"},
    {"limit": "-1", "offset": "-2", "includeTotal": "0"},
    {"limit": "300", "offset": "1.5"}, {"limit": "abc", "offset": "9e20"},
    {"q": "%", "platform": "pinduoduo", "includeTotal": "no"},
    {"capturedFrom": "2026-02-30"}, {"capturedFromTime": "2026-10-26T25:00:00"},
    {"capturedFrom": "2026-10-27", "capturedTo": "2026-10-26"},
    {"capturedFromTime": "2026-10-26T10:00:01", "capturedToTime": "2026-10-26T10:00:00"},
    {"productId": "1"}, {"platform": "unknown"}, {"groupId": "invalid"},
]

LEGACY = json.loads(subprocess.run(
    ["node", str(Path(__file__).parent / "fixtures/legacy-query-runner.mjs")],
    input=json.dumps(CASES), text=True, capture_output=True, check=True,
).stdout)


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


@pytest.mark.parametrize("params,expected", zip(CASES, LEGACY))
def test_matches_original_collector_query(params, expected):
    if "error" in expected:
        with pytest.raises(ProductRequestError, match=re.escape(expected["error"])):
            parse_product_list_options(params)
        return
    listing, count = build_product_list_queries(parse_product_list_options(params))
    assert normalized(listing.sql) == normalized(expected["queries"]["list"]["sql"])
    assert listing.params == expected["queries"]["list"]["params"]
    if count is None:
        assert expected["queries"]["count"] is None
    else:
        assert normalized(count.sql) == normalized(expected["queries"]["count"]["sql"])
        assert count.params == expected["queries"]["count"]["params"]


def test_list_excludes_payload_and_reuses_index_expression():
    listing, _ = build_product_list_queries(parse_product_list_options({"q": "商品"}))
    assert "uu_json" not in listing.sql
    assert "SELECT p.*" not in listing.sql
    assert "count(*) OVER" not in listing.sql
    assert "DESC NULLS LAST" in listing.sql
    db_sql, params = listing.dbapi()
    assert "$1" not in db_sql and "%(p1)s" in db_sql
    assert params["p1"] == "%商品%"
