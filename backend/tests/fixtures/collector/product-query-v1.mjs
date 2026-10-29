const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EXACT_PRODUCT_ID_PATTERN = /^(?:\d{8,}|[a-z][a-z0-9_-]{1,63}:\d{8,})$/i;

export function productSearchSql(alias = "p") {
  return `(COALESCE(${alias}.product_id, '') || E'\\x1F' ||
           COALESCE(${alias}.source_product_id, '') || E'\\x1F' ||
           COALESCE(${alias}.title, '') || E'\\x1F' ||
           COALESCE(${alias}.shop_name, '') || E'\\x1F' ||
           COALESCE(${alias}.category_path, ''))`;
}

export function parseProductListOptions(url) {
  const limit = boundedInteger(url.searchParams.get("limit"), 1, 200, 50);
  const offset = boundedInteger(url.searchParams.get("offset"), 0, 2_147_483_647, 0);
  const query = boundedText(url.searchParams.get("q"), 500);
  const productId = normalizeProductId(boundedText(url.searchParams.get("productId"), 128));
  const sourcePlatform = boundedText(url.searchParams.get("platform"), 64).toLowerCase();
  const groupId = boundedText(url.searchParams.get("groupId"), 64);
  const capturedFrom = dateParameter(url.searchParams.get("capturedFrom"), "采集开始日期");
  const capturedTo = dateParameter(url.searchParams.get("capturedTo"), "采集结束日期");
  const capturedFromTime = localDateTimeParameter(
    url.searchParams.get("capturedFromTime"),
    "采集开始时间",
  );
  const capturedToTime = localDateTimeParameter(
    url.searchParams.get("capturedToTime"),
    "采集结束时间",
  );
  const includeTotal = booleanParameter(url.searchParams.get("includeTotal"), true);

  if (productId && !EXACT_PRODUCT_ID_PATTERN.test(productId)) {
    throw requestError("商品 ID 精确检索值无效");
  }
  if (sourcePlatform && !["douyin", "pinduoduo"].includes(sourcePlatform)) {
    throw requestError("商品平台筛选无效");
  }
  if (groupId && groupId !== "ungrouped" && !UUID_PATTERN.test(groupId)) {
    throw requestError("商品分组筛选无效");
  }
  const effectiveCapturedFrom = capturedFromTime || (capturedFrom ? `${capturedFrom}T00:00:00` : "");
  const effectiveCapturedTo = capturedToTime || (capturedTo ? `${capturedTo}T23:59:59` : "");
  if (effectiveCapturedFrom && effectiveCapturedTo && effectiveCapturedFrom > effectiveCapturedTo) {
    throw requestError(
      capturedFromTime || capturedToTime
        ? "采集开始时间不能晚于结束时间"
        : "采集开始日期不能晚于结束日期",
    );
  }
  return {
    limit,
    offset,
    query,
    productId,
    sourcePlatform,
    groupId,
    capturedFrom,
    capturedTo,
    capturedFromTime,
    capturedToTime,
    includeTotal,
  };
}

export function buildProductListQueries(options) {
  const params = [];
  const where = [];

  if (options.productId) {
    params.push(options.productId);
    where.push(`(p.product_id = $${params.length} OR p.source_product_id = $${params.length})`);
  } else if (options.query) {
    params.push(`%${options.query}%`);
    const patternParameter = `$${params.length}`;
    // The expression index is a selective pre-filter. Keep the original
    // field-by-field OR as the final predicate so caller-supplied SQL wildcard
    // characters cannot match across two adjacent fields.
    where.push(`(${productSearchSql("p")} ILIKE ${patternParameter} AND (
      p.product_id ILIKE ${patternParameter}
      OR p.source_product_id ILIKE ${patternParameter}
      OR p.title ILIKE ${patternParameter}
      OR p.shop_name ILIKE ${patternParameter}
      OR p.category_path ILIKE ${patternParameter}
    ))`);
  }
  if (options.sourcePlatform) {
    params.push(options.sourcePlatform);
    where.push(`p.source_platform = $${params.length}`);
  }
  if (options.groupId === "ungrouped") {
    where.push("p.group_id IS NULL");
  } else if (options.groupId) {
    params.push(options.groupId);
    where.push(`p.group_id = $${params.length}`);
  }
  if (options.capturedFromTime) {
    params.push(options.capturedFromTime);
    where.push(`p.captured_at >= ($${params.length}::timestamp AT TIME ZONE 'Asia/Shanghai')`);
  } else if (options.capturedFrom) {
    params.push(options.capturedFrom);
    where.push(`p.captured_at >= ($${params.length}::date::timestamp AT TIME ZONE 'Asia/Shanghai')`);
  }
  if (options.capturedToTime) {
    params.push(options.capturedToTime);
    // The UI selects whole seconds. Use an exclusive next-second boundary so
    // rows with fractional precision inside the selected ending second remain
    // included without rounding captured_at.
    where.push(`p.captured_at < (($${params.length}::timestamp + interval '1 second') AT TIME ZONE 'Asia/Shanghai')`);
  } else if (options.capturedTo) {
    params.push(options.capturedTo);
    where.push(`p.captured_at < (($${params.length}::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')`);
  }

  const filterSql = where.length > 0 ? where.join(" AND ") : "true";
  const filterParams = [...params];
  params.push(options.limit);
  const limitParameter = params.length;
  params.push(options.offset);
  const offsetParameter = params.length;
  return {
    list: {
      sql: `SELECT p.product_id, p.source_platform, p.source_product_id, p.group_id,
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
             WHERE ${filterSql}
             ORDER BY p.captured_at DESC NULLS LAST, p.updated_at DESC, p.product_id
             LIMIT $${limitParameter} OFFSET $${offsetParameter}`,
      params,
    },
    count: options.includeTotal ? {
      sql: `SELECT count(*)::integer AS total FROM products p WHERE ${filterSql}`,
      params: filterParams,
    } : null,
  };
}

export async function listProducts(pool, url) {
  const options = parseProductListOptions(url);
  const queries = buildProductListQueries(options);
  if (!queries.count) {
    const listResult = await pool.query(queries.list.sql, queries.list.params);
    return productListResponse(options, listResult, null);
  }

  // List and total must describe one database snapshot. Parallel pool.query()
  // calls may use different connections and observe an insert/delete between
  // the two statements.
  const client = await pool.connect();
  let transactionStarted = false;
  try {
    await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
    transactionStarted = true;
    const listResult = await client.query(queries.list.sql, queries.list.params);
    const countResult = await client.query(queries.count.sql, queries.count.params);
    await client.query("COMMIT");
    transactionStarted = false;
    return productListResponse(options, listResult, countResult);
  } catch (error) {
    if (transactionStarted) await client.query("ROLLBACK").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

function productListResponse(options, listResult, countResult) {
  return {
    items: listResult.rows,
    total: countResult ? Number(countResult.rows[0]?.total || 0) : null,
    totalIncluded: Boolean(countResult),
    limit: options.limit,
    offset: options.offset,
  };
}

function normalizeProductId(value) {
  const separator = value.indexOf(":");
  if (separator < 0) return value;
  return `${value.slice(0, separator).toLowerCase()}${value.slice(separator)}`;
}

function boundedText(value, maximumLength) {
  return String(value ?? "").trim().slice(0, maximumLength);
}

function boundedInteger(value, minimum, maximum, fallback) {
  if (value == null || String(value).trim() === "") return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

function booleanParameter(value, fallback) {
  if (value == null || value === "") return fallback;
  return !["0", "false", "no"].includes(String(value).trim().toLowerCase());
}

function dateParameter(value, label) {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "";
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) throw requestError(`${label}无效`);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const calendarDate = new Date(Date.UTC(year, month - 1, day));
  if (calendarDate.getUTCFullYear() !== year
      || calendarDate.getUTCMonth() !== month - 1
      || calendarDate.getUTCDate() !== day) {
    throw requestError(`${label}无效`);
  }
  return normalized;
}

function localDateTimeParameter(value, label) {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "";
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) throw requestError(`${label}无效`);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] || 0);
  const calendarDate = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  if (calendarDate.getUTCFullYear() !== year
      || calendarDate.getUTCMonth() !== month - 1
      || calendarDate.getUTCDate() !== day
      || calendarDate.getUTCHours() !== hour
      || calendarDate.getUTCMinutes() !== minute
      || calendarDate.getUTCSeconds() !== second) {
    throw requestError(`${label}无效`);
  }
  return `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${String(second).padStart(2, "0")}`;
}

function requestError(message) {
  return Object.assign(new Error(message), { status: 400 });
}

