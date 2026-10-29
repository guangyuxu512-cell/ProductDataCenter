import { http } from '@/shared/api/http-client'
import type { Capabilities, NasDetail, ProductFilters, ProductGroup, ProductListResponse } from '../model/nas-contracts'

const EXACT_PRODUCT_ID = /^(?:\d{8,}|[a-z][a-z0-9_-]{1,63}:\d{8,})$/i

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
