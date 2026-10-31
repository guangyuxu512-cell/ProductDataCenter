-- 审查用迁移提案：由现有数据库迁移流程负责执行；商品云库启动不会执行本文件。
-- 依赖采集项目既有 products 表以及 0008 安装的 pg_trgm。
CREATE TABLE product_workbench_edits (
  product_id text PRIMARY KEY REFERENCES products(product_id) ON UPDATE CASCADE ON DELETE CASCADE,
  revision bigint NOT NULL CHECK (revision > 0),
  source_fingerprint char(64) NOT NULL,
  draft jsonb NOT NULL CHECK (jsonb_typeof(draft) = 'object'),
  display_title text GENERATED ALWAYS AS (draft ->> 'title') STORED,
  main_image_url text GENERATED ALWAYS AS (NULLIF(draft #>> '{mainImages,0,url}', '')) STORED,
  sku_count integer GENERATED ALWAYS AS (jsonb_array_length(draft -> 'skus')) STORED,
  main_image_count integer GENERATED ALWAYS AS (jsonb_array_length(draft -> 'mainImages')) STORED,
  detail_image_count integer GENERATED ALWAYS AS (jsonb_array_length(draft -> 'detailImages')) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX product_workbench_edits_title_trgm_idx
  ON product_workbench_edits USING gin (display_title gin_trgm_ops);
