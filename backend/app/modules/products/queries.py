"""从 product-query-v1.mjs 适配；SQL 保留现有表达式索引、排序和通配符语义。"""

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Mapping

from .errors import ProductRequestError

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
EXACT_PRODUCT_ID_PATTERN = re.compile(r"^(?:\d{8,}|[a-z][a-z0-9_-]{1,63}:\d{8,})$", re.I | re.ASCII)


def product_search_sql(alias: str = "p") -> str:
    return f"""(COALESCE({alias}.product_id, '') || E'\\x1F' ||
           COALESCE({alias}.source_product_id, '') || E'\\x1F' ||
           COALESCE({alias}.title, '') || E'\\x1F' ||
           COALESCE({alias}.shop_name, '') || E'\\x1F' ||
           COALESCE({alias}.category_path, ''))"""


def _bounded_integer(value: str | None, low: int, high: int, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        number = float(value)
        if not math.isfinite(number) or not number.is_integer() or abs(number) > 2**53 - 1:
            return default
        return min(high, max(low, int(number)))
    except ValueError:
        return default


def _date(value: str, label: str, *, time: bool = False) -> str:
    value = value.strip()
    if not value:
        return ""
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?" if time else r"\d{4}-\d{2}-\d{2}"
    try:
        if not re.fullmatch(pattern, value, flags=re.ASCII):
            raise ValueError()
        parsed = datetime.fromisoformat(value)
        if parsed.year < 100:  # JS Date.UTC 0..99 uses 1900..1999 and fails source round-trip.
            raise ValueError()
        return parsed.isoformat(timespec="seconds") if time else parsed.date().isoformat()
    except ValueError:
        raise ProductRequestError(f"{label}无效") from None


@dataclass(frozen=True)
class ProductListOptions:
    limit: int = 50
    offset: int = 0
    query: str = ""
    product_id: str = ""
    source_platform: str = ""
    group_id: str = ""
    captured_from: str = ""
    captured_to: str = ""
    captured_from_time: str = ""
    captured_to_time: str = ""
    include_total: bool = True


def parse_product_list_options(params: Mapping[str, str]) -> ProductListOptions:
    def value(key: str, length: int = 500) -> str:
        return params.get(key, "").strip()[:length]

    product_id = value("productId", 128)
    if ":" in product_id:
        prefix, suffix = product_id.split(":", 1)
        product_id = f"{prefix.lower()}:{suffix}"
    platform, group_id = value("platform", 64).lower(), value("groupId", 64)
    if product_id and not EXACT_PRODUCT_ID_PATTERN.fullmatch(product_id):
        raise ProductRequestError("商品 ID 精确检索值无效")
    if platform and platform not in {"douyin", "pinduoduo"}:
        raise ProductRequestError("商品平台筛选无效")
    if group_id and group_id != "ungrouped" and not UUID_PATTERN.fullmatch(group_id):
        raise ProductRequestError("商品分组筛选无效")
    start = _date(params.get("capturedFrom", ""), "采集开始日期")
    end = _date(params.get("capturedTo", ""), "采集结束日期")
    start_time = _date(params.get("capturedFromTime", ""), "采集开始时间", time=True)
    end_time = _date(params.get("capturedToTime", ""), "采集结束时间", time=True)
    lower = start_time or (f"{start}T00:00:00" if start else "")
    upper = end_time or (f"{end}T23:59:59" if end else "")
    if lower and upper and lower > upper:
        label = "时间" if start_time or end_time else "日期"
        raise ProductRequestError(f"采集开始{label}不能晚于结束{label}")
    return ProductListOptions(
        limit=_bounded_integer(params.get("limit"), 1, 200, 50),
        offset=_bounded_integer(params.get("offset"), 0, 2_147_483_647, 0),
        query=value("q"), product_id=product_id, source_platform=platform, group_id=group_id,
        captured_from=start, captured_to=end, captured_from_time=start_time, captured_to_time=end_time,
        include_total=value("includeTotal").lower() not in {"0", "false", "no"},
    )


@dataclass(frozen=True)
class Query:
    sql: str
    params: list

    def dbapi(self) -> tuple[str, dict]:
        return re.sub(r"\$(\d+)", lambda m: f"%(p{m[1]})s", self.sql), {
            f"p{i}": value for i, value in enumerate(self.params, 1)
        }


def build_product_list_queries(options: ProductListOptions) -> tuple[Query, Query | None]:
    params: list = []
    where: list[str] = []

    def bind(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if options.product_id:
        p = bind(options.product_id)
        where.append(f"(p.product_id = {p} OR p.source_product_id = {p})")
    elif options.query:
        p = bind(f"%{options.query}%")
        where.append(f"""({product_search_sql()} ILIKE {p} AND (
      p.product_id ILIKE {p}
      OR p.source_product_id ILIKE {p}
      OR p.title ILIKE {p}
      OR p.shop_name ILIKE {p}
      OR p.category_path ILIKE {p}
    ))""")
    if options.source_platform:
        where.append(f"p.source_platform = {bind(options.source_platform)}")
    if options.group_id == "ungrouped":
        where.append("p.group_id IS NULL")
    elif options.group_id:
        where.append(f"p.group_id = {bind(options.group_id)}")
    if options.captured_from_time:
        where.append(f"p.captured_at >= ({bind(options.captured_from_time)}::timestamp AT TIME ZONE 'Asia/Shanghai')")
    elif options.captured_from:
        where.append(f"p.captured_at >= ({bind(options.captured_from)}::date::timestamp AT TIME ZONE 'Asia/Shanghai')")
    if options.captured_to_time:
        where.append(f"p.captured_at < (({bind(options.captured_to_time)}::timestamp + interval '1 second') AT TIME ZONE 'Asia/Shanghai')")
    elif options.captured_to:
        where.append(f"p.captured_at < (({bind(options.captured_to)}::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')")
    filters = " AND ".join(where) or "true"
    count = Query(f"SELECT count(*)::integer AS total FROM products p WHERE {filters}", params.copy()) if options.include_total else None
    limit, offset = bind(options.limit), bind(options.offset)
    query = Query(f"""SELECT p.product_id, p.source_platform, p.source_product_id, p.group_id,
                   g.group_name, p.title, p.title_status, p.shop_name,
                   p.category_level_4, p.category_path,
                   p.current_price_min, p.current_price_max, p.sku_count,
                   p.main_image_count, p.detail_image_count, p.sku_image_count,
                   (SELECT pi.source_url
                      FROM product_images pi
                     WHERE pi.product_id = p.product_id
                       AND pi.image_type = 'main'
                       AND pi.source_url <> ''
                     ORDER BY pi.sort_order
                     LIMIT 1) AS main_image_url,
                   p.asset_rel_path, p.workbook_rel_path, p.raw_rel_path,
                   p.captured_at, p.updated_at
              FROM products p
              LEFT JOIN product_groups g ON g.group_id = p.group_id
             WHERE {filters}
             ORDER BY p.captured_at DESC NULLS LAST, p.updated_at DESC, p.product_id
             LIMIT {limit} OFFSET {offset}""", params)
    return query, count
