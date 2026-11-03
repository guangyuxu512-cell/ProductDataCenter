-- Queue only new or changed packages. Existing products are not rechecked by migration.
CREATE TABLE product_prechecks (
  product_id text PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
  revision bigint NOT NULL DEFAULT 1,
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'done')),
  attempts integer NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz,
  result jsonb,
  last_error text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX product_prechecks_pending_idx
  ON product_prechecks (available_at, product_id)
  WHERE state IN ('pending', 'running');

CREATE FUNCTION collector_queue_product_precheck()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.uu_json IS NOT DISTINCT FROM NEW.uu_json THEN
    RETURN NEW;
  END IF;
  IF NEW.uu_json IS NULL THEN
    DELETE FROM public.product_prechecks WHERE product_id = NEW.product_id;
  ELSE
    INSERT INTO public.product_prechecks (product_id) VALUES (NEW.product_id)
    ON CONFLICT (product_id) DO UPDATE SET
      revision = product_prechecks.revision + 1, state = 'pending', attempts = 0,
      available_at = now(), lease_until = NULL, result = NULL, last_error = NULL, updated_at = now();
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER products_queue_precheck
AFTER INSERT OR UPDATE OF uu_json ON products
FOR EACH ROW EXECUTE FUNCTION collector_queue_product_precheck();
