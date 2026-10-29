CREATE FUNCTION collector_try_jsonb(value text)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
  RETURN COALESCE(value, '{}')::jsonb;
EXCEPTION WHEN others THEN
  RETURN '{}'::jsonb;
END;
$$;

CREATE FUNCTION collector_storefront_price(sku jsonb)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  business jsonb := collector_try_jsonb(sku->>'extra_business_info');
  cents text;
  visible text[];
BEGIN
  cents := NULLIF(business #>> '{first_price,left_price_num}', '');
  IF cents IS NOT NULL THEN
    RETURN cents::numeric / 100;
  END IF;

  visible := regexp_match(COALESCE(sku->>'aria_label_price', ''), '[￥¥]([0-9]+([.][0-9]+)?)');
  IF visible IS NOT NULL THEN
    RETURN visible[1]::numeric;
  END IF;

  cents := NULLIF(business #>> '{second_price,left_price_num}', '');
  IF cents IS NOT NULL THEN
    RETURN cents::numeric / 100;
  END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION collector_apply_product_storefront_prices()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  sku jsonb;
  price numeric;
  lowest numeric;
  highest numeric;
BEGIN
  IF NEW.source_platform <> 'douyin'
     OR jsonb_typeof(NEW.uu_json #> '{goodsInfo,skuInfoMap}') <> 'object' THEN
    RETURN NEW;
  END IF;

  FOR sku IN SELECT value FROM jsonb_each(NEW.uu_json #> '{goodsInfo,skuInfoMap}')
  LOOP
    price := collector_storefront_price(sku);
    IF price IS NOT NULL THEN
      lowest := CASE WHEN lowest IS NULL THEN price ELSE LEAST(lowest, price) END;
      highest := CASE WHEN highest IS NULL THEN price ELSE GREATEST(highest, price) END;
    END IF;
  END LOOP;

  IF lowest IS NOT NULL THEN
    NEW.current_price_min := lowest;
    NEW.current_price_max := highest;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER products_storefront_prices
BEFORE INSERT OR UPDATE OF uu_json, current_price_min, current_price_max ON products
FOR EACH ROW EXECUTE FUNCTION collector_apply_product_storefront_prices();

CREATE FUNCTION collector_apply_sku_storefront_price()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  sku jsonb;
  price numeric;
BEGIN
  SELECT item.value
    INTO sku
    FROM products product
    CROSS JOIN LATERAL jsonb_each(COALESCE(product.uu_json #> '{goodsInfo,skuInfoMap}', '{}')) item
   WHERE product.product_id = NEW.product_id
     AND COALESCE(item.value->>'sku_id', item.value->>'skuId', item.value->>'id', '') = NEW.sku_id
   LIMIT 1;

  price := collector_storefront_price(sku);
  IF price IS NOT NULL THEN
    NEW.current_price := price;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER product_skus_storefront_price
BEFORE INSERT OR UPDATE OF current_price ON product_skus
FOR EACH ROW EXECUTE FUNCTION collector_apply_sku_storefront_price();

