CREATE TABLE product_groups (
  group_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX product_groups_name_ci_idx
  ON product_groups ((lower(group_name)));

ALTER TABLE products ADD COLUMN group_id uuid
  REFERENCES product_groups(group_id) ON UPDATE CASCADE ON DELETE SET NULL;

CREATE INDEX products_platform_captured_at_idx
  ON products (source_platform, captured_at DESC, updated_at DESC, product_id);
CREATE INDEX products_group_captured_at_idx
  ON products (group_id, captured_at DESC, updated_at DESC, product_id);

CREATE TRIGGER product_groups_set_updated_at
BEFORE UPDATE ON product_groups
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE VIEW listing_products AS
SELECT
  p.product_id,
  p.title,
  p.shop_name,
  p.category_path,
  p.current_price_min,
  p.current_price_max,
  p.sku_count,
  p.asset_rel_path,
  p.workbook_rel_path,
  p.captured_at,
  p.updated_at,
  p.group_id,
  g.group_name
FROM products p
LEFT JOIN product_groups g ON g.group_id = p.group_id;
