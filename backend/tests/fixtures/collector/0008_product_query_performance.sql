CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The original DESC indexes use PostgreSQL's default NULLS FIRST ordering,
-- while the product page explicitly requests NULLS LAST. Rebuild the same
-- logical indexes with the ordering used by the API so PostgreSQL can stop
-- after the requested page instead of sorting every matching product.
DROP INDEX products_captured_at_idx;
CREATE INDEX products_captured_at_idx
  ON products (captured_at DESC NULLS LAST, updated_at DESC, product_id);

DROP INDEX products_platform_captured_at_idx;
CREATE INDEX products_platform_captured_at_idx
  ON products (source_platform, captured_at DESC NULLS LAST, updated_at DESC, product_id);

DROP INDEX products_group_captured_at_idx;
CREATE INDEX products_group_captured_at_idx
  ON products (group_id, captured_at DESC NULLS LAST, updated_at DESC, product_id);

-- A single expression preserves the existing substring search across all five
-- fields without paying for five separate GIN indexes. The unit separator keeps
-- values from adjacent fields from being mistaken for one contiguous value.
CREATE INDEX products_search_trgm_idx
  ON products USING gin ((
    COALESCE(product_id, '') || E'\x1F' ||
    COALESCE(source_product_id, '') || E'\x1F' ||
    COALESCE(title, '') || E'\x1F' ||
    COALESCE(shop_name, '') || E'\x1F' ||
    COALESCE(category_path, '')
  ) gin_trgm_ops);

