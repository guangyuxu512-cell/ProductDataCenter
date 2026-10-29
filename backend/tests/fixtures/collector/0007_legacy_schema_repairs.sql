DO $migration$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_constraint
     WHERE conrelid = 'public.collection_jobs'::regclass
       AND conname = 'collection_jobs_job_type_check'
  ) THEN
    IF EXISTS (
      SELECT 1
        FROM collection_jobs
       WHERE job_type IS NULL
          OR job_type NOT IN ('product', 'store')
    ) THEN
      RAISE EXCEPTION
        'collection_jobs contains job_type values outside product/store';
    END IF;

    ALTER TABLE collection_jobs
      ADD CONSTRAINT collection_jobs_job_type_check
      CHECK (job_type IN ('product', 'store')) NOT VALID;

    ALTER TABLE collection_jobs
      VALIDATE CONSTRAINT collection_jobs_job_type_check;
  END IF;

  IF NOT EXISTS (
    SELECT 1
      FROM pg_trigger trigger_entry
     WHERE trigger_entry.tgrelid = 'public.capture_ingest'::regclass
       AND trigger_entry.tgname = 'capture_ingest_set_updated_at'
       AND NOT trigger_entry.tgisinternal
  ) THEN
    CREATE TRIGGER capture_ingest_set_updated_at
    BEFORE UPDATE ON capture_ingest
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END
$migration$;
