CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE devices (
  device_id text PRIMARY KEY,
  display_name text NOT NULL DEFAULT '',
  android_serial text NOT NULL DEFAULT '',
  wifi_endpoint text NOT NULL DEFAULT '',
  credential_hash text NOT NULL DEFAULT '',
  credential_issued_at timestamptz,
  credential_revoked_at timestamptz,
  manufacturer text NOT NULL DEFAULT '',
  model text NOT NULL DEFAULT '',
  android_version text NOT NULL DEFAULT '',
  automation_version text NOT NULL DEFAULT '',
  collector_version text NOT NULL DEFAULT '',
  connection_mode text NOT NULL DEFAULT 'network',
  runtime_state text NOT NULL DEFAULT 'offline',
  current_job_id uuid,
  screen_interactive boolean,
  battery_percent integer,
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
  settings jsonb NOT NULL DEFAULT '{"wakeBeforeTask":true,"keepScreenOn":true,"sleepAfterIdle":true,"sleepDelaySeconds":60,"restEnabled":false}'::jsonb,
  last_seen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX devices_credential_hash_idx
  ON devices (credential_hash) WHERE credential_hash <> '';

CREATE TABLE device_pairing_codes (
  pairing_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code_hash char(64) NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  device_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX device_pairing_codes_expiry_idx
  ON device_pairing_codes (expires_at) WHERE used_at IS NULL;

CREATE TABLE collection_jobs (
  job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_job_id text UNIQUE,
  product_id text,
  job_type text NOT NULL DEFAULT 'product'
    CHECK (job_type IN ('product', 'store')),
  source_type text NOT NULL DEFAULT 'manual',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'running', 'retry_wait', 'captured', 'converted', 'completed', 'failed', 'canceled')),
  priority integer NOT NULL DEFAULT 0,
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  device_id text REFERENCES devices(device_id) ON UPDATE CASCADE ON DELETE SET NULL,
  last_error text NOT NULL DEFAULT '',
  next_attempt_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX collection_jobs_status_idx
  ON collection_jobs (status, priority DESC, created_at);
CREATE INDEX collection_jobs_product_idx
  ON collection_jobs (product_id, created_at DESC);
CREATE UNIQUE INDEX collection_jobs_active_product_idx
  ON collection_jobs (product_id)
  WHERE job_type = 'product'
    AND product_id IS NOT NULL
    AND status IN ('pending', 'running', 'retry_wait', 'captured', 'converted');

CREATE TABLE captures (
  capture_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid REFERENCES collection_jobs(job_id) ON UPDATE CASCADE ON DELETE SET NULL,
  product_id text NOT NULL,
  device_id text NOT NULL DEFAULT '',
  remote_file text NOT NULL,
  local_raw_rel_path text NOT NULL DEFAULT '',
  sha256 char(64) NOT NULL DEFAULT '',
  detail_complete boolean NOT NULL DEFAULT false,
  sku_complete boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'discovered'
    CHECK (status IN ('discovered', 'pulled', 'verified', 'converted', 'acknowledged', 'remote_deleted', 'failed')),
  captured_at timestamptz,
  pulled_at timestamptz,
  verified_at timestamptz,
  converted_at timestamptz,
  acknowledged_at timestamptz,
  remote_deleted_at timestamptz,
  last_error text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (device_id, remote_file)
);

CREATE INDEX captures_cleanup_idx
  ON captures (status, acknowledged_at)
  WHERE status = 'acknowledged';
CREATE INDEX captures_product_idx
  ON captures (product_id, captured_at DESC);

CREATE TABLE products (
  product_id text PRIMARY KEY,
  title text NOT NULL DEFAULT '',
  title_status text NOT NULL DEFAULT '',
  shop_id text NOT NULL DEFAULT '',
  shop_name text NOT NULL DEFAULT '',
  category_level_1 text NOT NULL DEFAULT '',
  category_level_2 text NOT NULL DEFAULT '',
  category_level_3 text NOT NULL DEFAULT '',
  category_level_4 text NOT NULL DEFAULT '',
  category_path text NOT NULL DEFAULT '',
  category_leaf_id text NOT NULL DEFAULT '',
  current_price_min numeric(12, 2),
  current_price_max numeric(12, 2),
  sku_count integer NOT NULL DEFAULT 0,
  main_image_count integer NOT NULL DEFAULT 0,
  detail_image_count integer NOT NULL DEFAULT 0,
  sku_image_count integer NOT NULL DEFAULT 0,
  asset_rel_path text NOT NULL DEFAULT '',
  workbook_rel_path text NOT NULL DEFAULT '',
  raw_rel_path text NOT NULL DEFAULT '',
  captured_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX products_captured_at_idx ON products (captured_at DESC);
CREATE INDEX products_shop_name_idx ON products (shop_name);
CREATE INDEX products_category_path_idx ON products (category_path);

CREATE TABLE product_skus (
  product_id text NOT NULL REFERENCES products(product_id) ON UPDATE CASCADE ON DELETE CASCADE,
  sku_id text NOT NULL,
  sku_name text NOT NULL DEFAULT '',
  current_price numeric(12, 2),
  image_rel_path text NOT NULL DEFAULT '',
  sort_order integer NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (product_id, sku_id)
);

CREATE TABLE product_images (
  product_id text NOT NULL REFERENCES products(product_id) ON UPDATE CASCADE ON DELETE CASCADE,
  image_type text NOT NULL CHECK (image_type IN ('main', 'detail', 'sku')),
  sort_order integer NOT NULL,
  rel_path text NOT NULL,
  source_url text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (product_id, image_type, sort_order)
);

CREATE TABLE collector_settings (
  setting_key text PRIMARY KEY,
  setting_value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO collector_settings (setting_key, setting_value) VALUES
  ('phone_cleanup', '{"enabled":true,"acknowledged_batch_size":10,"keep_recent":3}'::jsonb),
  ('retry_policy', '{"max_attempts":3,"delays_seconds":[5,15,30]}'::jsonb);

CREATE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER devices_set_updated_at
BEFORE UPDATE ON devices
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER collection_jobs_set_updated_at
BEFORE UPDATE ON collection_jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER captures_set_updated_at
BEFORE UPDATE ON captures
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER products_set_updated_at
BEFORE UPDATE ON products
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE VIEW listing_products AS
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
  p.updated_at
FROM products p;
