/** 已核对 mobile-product-collector 商品 API；来源 ID 始终为字符串。 */
export interface ProductRow {
  product_id: string
  source_platform: string
  source_product_id: string | null
  group_id: string | null
  group_name: string | null
  title: string
  title_status: string
  shop_name: string
  category_level_4: string
  category_path: string
  current_price_min: string | null
  current_price_max: string | null
  sku_count: number
  main_image_count: number
  detail_image_count: number
  sku_image_count: number
  main_image_url: string | null
  captured_at: string | null
  updated_at: string | null
  asset_rel_path: string
  workbook_rel_path: string
  raw_rel_path: string
}

export interface ProductListResponse {
  items: ProductRow[]
  total: number | null
  totalIncluded: boolean
  limit: number
  offset: number
}

export interface NasDetail {
  product: ProductRow
  skus: Array<{ sku_id: string; sku_name: string; current_price: string | null; image_rel_path: string; sort_order: number }>
  images: Array<{ image_type: 'main' | 'detail' | 'sku'; sort_order: number; rel_path: string; source_url: string }>
}

export interface ProductGroup {
  groupId: string
  name: string
  productCount: number
}

export interface ProductFilters {
  query: string
  platform: '' | 'douyin' | 'pinduoduo' | 'manual'
  groupId: string
  capturedFrom: string
  capturedTo: string
  page: number
  pageSize: number
}

export interface Capabilities {
  groupWrites: boolean
  export: boolean
  productEdit: boolean
  manualCreate?: boolean
  assetUploads?: boolean
  importProducts: boolean
}
