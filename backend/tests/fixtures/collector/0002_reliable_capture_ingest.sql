ALTER TABLE collection_jobs ADD COLUMN source_platform text NOT NULL DEFAULT 'douyin';
ALTER TABLE collection_jobs ADD COLUMN source_product_id text;
ALTER TABLE collection_jobs ADD COLUMN recapture_requested boolean NOT NULL DEFAULT false;
ALTER TABLE collection_jobs ADD COLUMN capture_batch_id uuid;
ALTER TABLE collection_jobs ADD COLUMN result_capture_id uuid;

UPDATE collection_jobs
   SET source_product_id = product_id
 WHERE source_product_id IS NULL AND product_id IS NOT NULL;

DROP INDEX collection_jobs_product_idx;
CREATE INDEX collection_jobs_product_idx
  ON collection_jobs (source_platform, source_product_id, created_at DESC);
DROP INDEX collection_jobs_active_product_idx;
CREATE UNIQUE INDEX collection_jobs_active_product_idx
  ON collection_jobs (source_platform, source_product_id)
  WHERE job_type = 'product'
    AND source_product_id IS NOT NULL
    AND status IN ('pending', 'running', 'retry_wait', 'captured', 'converted');

ALTER TABLE captures ADD COLUMN source_platform text NOT NULL DEFAULT 'douyin';
ALTER TABLE captures ADD COLUMN source_product_id text;
ALTER TABLE captures ADD COLUMN receipt_id uuid;
ALTER TABLE captures ADD COLUMN capture_batch_id uuid;

UPDATE captures
   SET source_product_id = product_id
 WHERE source_product_id IS NULL;

CREATE UNIQUE INDEX captures_receipt_idx ON captures (receipt_id);

ALTER TABLE products ADD COLUMN source_platform text NOT NULL DEFAULT 'douyin';
ALTER TABLE products ADD COLUMN source_product_id text;
ALTER TABLE products ADD COLUMN uu_json jsonb;
ALTER TABLE products ADD COLUMN uu_rel_path text NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN uu_sha256 char(64) NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN latest_capture_id uuid;

UPDATE products
   SET source_product_id = product_id
 WHERE source_product_id IS NULL;

CREATE UNIQUE INDEX products_source_identity_idx
  ON products (source_platform, source_product_id);

CREATE TABLE capture_ingest (
  receipt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  upload_key char(64) NOT NULL UNIQUE,
  job_id uuid REFERENCES collection_jobs(job_id) ON UPDATE CASCADE ON DELETE SET NULL,
  capture_batch_id uuid,
  source_platform text NOT NULL,
  source_product_id text NOT NULL,
  device_id text NOT NULL,
  remote_file text NOT NULL,
  raw_rel_path text NOT NULL,
  staging_rel_path text NOT NULL,
  content_sha256 char(64) NOT NULL,
  status text NOT NULL DEFAULT 'received'
    CONSTRAINT capture_ingest_status_check
    CHECK (status IN ('received', 'processing', 'succeeded', 'failed', 'superseded')),
  process_attempts integer NOT NULL DEFAULT 0,
  max_process_attempts integer NOT NULL DEFAULT 3,
  next_attempt_at timestamptz,
  capture_id uuid,
  uu_rel_path text NOT NULL DEFAULT '',
  uu_sha256 char(64) NOT NULL DEFAULT '',
  applied_to_product boolean NOT NULL DEFAULT false,
  captured_at timestamptz,
  received_at timestamptz NOT NULL DEFAULT now(),
  processing_started_at timestamptz,
  processed_at timestamptz,
  last_error text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX capture_ingest_processing_idx
  ON capture_ingest (status, next_attempt_at, received_at);
CREATE INDEX capture_ingest_job_idx
  ON capture_ingest (job_id, capture_batch_id, received_at DESC);

CREATE TRIGGER capture_ingest_set_updated_at
BEFORE UPDATE ON capture_ingest
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
