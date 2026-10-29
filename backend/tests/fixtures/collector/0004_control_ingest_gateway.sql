ALTER TABLE devices ADD COLUMN assignment_capabilities jsonb NOT NULL DEFAULT
  '{"platforms":["douyin"],"ingestProtocols":["gateway_v1"]}'::jsonb;

ALTER TABLE collection_jobs ADD COLUMN canonical_payload_hash char(64);
ALTER TABLE collection_jobs ADD COLUMN control_dispatch_id uuid;
ALTER TABLE collection_jobs ADD COLUMN ingest_mode text NOT NULL DEFAULT 'gateway_v1';
ALTER TABLE collection_jobs ADD COLUMN lease_expires_at timestamptz;
ALTER TABLE collection_jobs ADD COLUMN control_attempt_id uuid;
ALTER TABLE collection_jobs ADD COLUMN control_credential_id text NOT NULL DEFAULT '';
ALTER TABLE collection_jobs ADD COLUMN control_credential_expires_at timestamptz;
ALTER TABLE collection_jobs ADD COLUMN control_settlement_receipt_id uuid;
ALTER TABLE collection_jobs ADD COLUMN control_result jsonb;

ALTER TABLE capture_ingest DROP CONSTRAINT capture_ingest_status_check;
ALTER TABLE capture_ingest ADD CONSTRAINT capture_ingest_status_check
  CHECK (status IN (
    'received', 'processing', 'relay_pending', 'relayed',
    'succeeded', 'failed', 'superseded'
  ));
