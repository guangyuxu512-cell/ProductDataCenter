import type { PlatformCode } from '@/entities/platform/model/registry'

export interface ProductGroup {
  id: string
  name: string
  count: number | null
}

export interface ProductSku {
  /** Stable frontend identity for saved and unsaved SKU rows. */
  draftKey: string
  /** Platform source identity. Frontend-created SKUs intentionally have none. */
  sourceSkuId: string | null
  name: string
  currentPrice: string | null
  stockLabel: string | null
  imageUrl: string | null
  /** Frontend/Mock editing draft only; keys bind explicitly to specDimensions. */
  specValues: Record<string, string>
}

export interface ProductSpecDimension {
  id: string
  name: string
}

export interface ProductEditSku {
  draftKey: string
  sourceSkuId: string | null
  name: string
  currentPrice: string | null
  imageUrl: string | null
  specValues: Record<string, string>
}

export interface ProductEditDraft {
  title: string
  attributes: Array<{ name: string; value: string }>
  specDimensions: ProductSpecDimension[]
  skus: ProductEditSku[]
}

export interface ProductHistory {
  id: string
  collectedAt: string
  state: 'completed' | 'partial' | 'failed'
  summary: string
}

export interface LibraryProduct {
  id: string
  productId: string
  platform: PlatformCode
  title: string
  shopName?: string
  skuCount?: number
  mainImageCount?: number
  detailImageCount?: number
  skuImageCount?: number
  groupId: string | null
  groupName: string | null
  category: string | null
  currentPrice: string | null
  currency?: string | null
  collectedAt: string
  sourceUrl: string | null
  mainImageUrl: string | null
  /** Frontend/Mock preview draft only; this is not a Backend DTO field. */
  previewMainImageUrls?: string[]
  detailImageUrls: string[]
  /** Frontend/Mock editing draft only; this is not a Backend DTO field. */
  specDimensions: ProductSpecDimension[]
  skus: ProductSku[]
  attributes: Array<{ name: string; value: string }>
  mockEditedAt: string | null
  packageFiles: Array<{ name: string; kind: 'txt' | 'origin-txt' | 'image' }>
  history: ProductHistory[]
  latestCollectionState?: string | null
  latestCollectionErrorCode?: string | null
}

export interface ProductLibraryQuery {
  /** Frontend/Mock view draft; the Real query contract is not frozen. */
  view?: ProductLibraryView
  keyword: string
  platform: PlatformCode | null
  groupId: string | null
  category: string | null
  page: number
  pageSize: number
}

export type ProductLibraryView = 'all' | 'ungrouped' | 'grouped'

export interface ProductLibraryPage {
  items: LibraryProduct[]
  total: number
  page: number
  pageSize: number
  categories: string[]
}

export interface ProductLibraryExportFile {
  fileName: string
  content: string
}

export interface ProductLibraryService {
  available: boolean
  mode: 'mock' | 'real'
  capabilities: {
    platformFilter: boolean
    categoryFilter: boolean
    edit: boolean
    createGroup: boolean
    moveGroup: boolean
    remove: boolean
    recollect: boolean
    import: boolean
    /** Single adopted UU snapshot exported as its original JSON TXT. */
    export: boolean
    /** Multi-product archive/list export remains a separate capability. */
    batchExport: boolean
  }
  groups(): Promise<ProductGroup[]>
  list(query: ProductLibraryQuery): Promise<ProductLibraryPage>
  detail(id: string): Promise<LibraryProduct>
  saveEdit(id: string, draft: ProductEditDraft): Promise<LibraryProduct>
  createGroup(name: string): Promise<ProductGroup>
  moveToGroup(ids: string[], groupId: string | null): Promise<number>
  remove(ids: string[]): Promise<number>
  recollect(ids: string[]): Promise<number>
  exportSingle(id: string): Promise<ProductLibraryExportFile>
}

