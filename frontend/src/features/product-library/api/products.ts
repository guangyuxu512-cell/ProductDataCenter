import { http } from '@/shared/api/http-client'
import type { Capabilities, NasDetail, ProductFilters, ProductGroup, ProductListResponse } from '../model/nas-contracts'
import type { AutoPrecheck } from '../model/precheck'

export async function uploadProductImage(file: File) {
  return (await http.post<{ url: string }>('/product-images', file, {
    headers: { 'Content-Type': file.type || 'application/octet-stream' }, timeout: 120_000,
  })).data
}

const EXACT_PRODUCT_ID = /^(?:\d{8,}|[a-z][a-z0-9_-]{1,63}:\d{8,})$/i

export interface SpecImage { id: string; name: string; url: string }
export interface SpecGroup { index: number; name: string; values: SpecImage[]; movable: boolean; sourceIndex?: number | null }
export interface EditableSku { skuId: string; specIds: string[]; price: string; stock: number | null; enabled: boolean | null; merchantCode: string }
export interface EditSnapshot { version: string; specImageGroup: string; specImages: SpecImage[]; specGroups?: SpecGroup[]; specImagesEditable?: boolean; skus: EditableSku[] }
export interface ProductPatch {
  expectedVersion: string
  title?: string
  category?: Array<{ id: string; name: string }>
  attributes?: Array<{ id: string; name: string; values: Array<{ valueId: string; name: string }> }>
  mainImages?: string[]
  detailImages?: string[]
  specImages?: Array<{ specId: string; url: string }>
  specImageGroupIndex?: number
  skus?: Array<{ specIds: string[]; price?: string; stock?: number; merchantCode?: string; enabled?: boolean; delete?: boolean }>
  specStructure?: {
    groups: Array<{ sourceIndex: number | null; name: string; values: SpecImage[] }>
    skus: Array<{ sourceSpecIds: string[] | null; specIds: string[]; price: string; stock: string; merchantCode: string; enabled: boolean | null }>
  }
}

export async function fetchEditSnapshot(id: string) {
  return (await http.get<EditSnapshot>(`/products/${encodeURIComponent(id)}/edit`)).data
}

export async function saveProduct(id: string, patch: ProductPatch) {
  return (await http.patch<{ version: string }>(`/products/${encodeURIComponent(id)}`, patch)).data
}

export async function createManualProduct(title: string, draftSeed?: string, edit?: ProductPatch) {
  return (await http.post<{ productId: string }>('/products', { title, draftSeed, edit })).data
}

export async function fetchAutoPrechecks(productIds: string[], signal?: AbortSignal) {
  return (await http.post<{ items: AutoPrecheck[] }>('/prechecks/query', { productIds }, { signal })).data.items
}

export interface ResolvedProductCategory {
  productId: string
  status: 'resolved' | 'unavailable' | 'unsupported'
  path: string
  levels: Array<{ id: string; name: string }>
}

export async function resolveProductCategories(productIds: string[], signal?: AbortSignal) {
  return (await http.post<{ items: ResolvedProductCategory[] }>('/category-lookup/resolve-products',
    { productIds }, { signal, timeout: 120_000 })).data.items
}

export async function queuePrechecks(productIds: string[]) {
  return (await http.post<{ items: AutoPrecheck[]; missing: string[] }>('/prechecks/run', { productIds })).data
}

export function productListParams(filters: ProductFilters, includeTotal: boolean) {
  return {
    q: filters.query.trim(),
    productId: EXACT_PRODUCT_ID.test(filters.query.trim()) ? filters.query.trim() : undefined,
    platform: filters.platform, groupId: filters.groupId,
    capturedFromTime: filters.capturedFrom, capturedToTime: filters.capturedTo,
    limit: filters.pageSize, offset: (filters.page - 1) * filters.pageSize, includeTotal,
  }
}

export async function fetchProducts(filters: ProductFilters, includeTotal: boolean, signal?: AbortSignal) {
  return (await http.get<ProductListResponse>('/products', { params: productListParams(filters, includeTotal), signal })).data
}

export async function fetchGroups(signal?: AbortSignal) {
  return (await http.get<{ groups: ProductGroup[] }>('/product-groups', { signal })).data.groups
}

export async function fetchCapabilities(signal?: AbortSignal) {
  return (await http.get<Capabilities>('/capabilities', { signal })).data
}

export async function saveGroup(name: string, groupId?: string) {
  const body = { name }
  return groupId
    ? (await http.patch(`/product-groups/${encodeURIComponent(groupId)}`, body)).data
    : (await http.post('/product-groups', body)).data
}

export async function deleteGroup(groupId: string) {
  return (await http.delete(`/product-groups/${encodeURIComponent(groupId)}`)).data
}

export async function moveProducts(productIds: string[], groupId: string | null) {
  return (await http.patch<{ updated: string[] }>('/products/group', { productIds, groupId })).data
}

export async function deleteProducts(productIds: string[]) {
  return (await http.post<{ deleted: string[]; missing: string[] }>('/products/delete', { productIds })).data
}

export async function fetchDetail(id: string, signal?: AbortSignal) {
  return (await http.get<NasDetail>(`/products/${encodeURIComponent(id)}`, { signal })).data
}

export async function exportProducts(productIds: string[]) {
  try {
    const response = await http.post<Blob>('/products/export-uu', { productIds }, { responseType: 'blob', timeout: 120_000 })
    const filename = String(response.headers['content-disposition'] ?? '').match(/filename="([^"]+)"/)?.[1] ?? 'uu-export.zip'
    return { blob: response.data, filename, exported: Number(response.headers['x-export-count'] ?? 0), missing: Number(response.headers['x-export-missing-count'] ?? 0) }
  } catch (error) {
    const response = (error as { response?: { data?: Blob } }).response
    if (response?.data instanceof Blob) {
      const message = await response.data.text().then((value) => JSON.parse(value).message).catch(() => null)
      if (typeof message === 'string') throw new Error(message)
    }
    throw error
  }
}
