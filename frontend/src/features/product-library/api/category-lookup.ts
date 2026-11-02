import { http } from '@/shared/api/http-client'

export interface CategoryCandidate { id: string; name: string; path: string }
export interface CategoryAttribute {
  id: string
  label: string
  required: boolean
  options: Array<{ label: string; value: string }>
}

export async function searchCategoryCandidates(keyword: string) {
  return (await http.post<{ shopId: string; candidates: CategoryCandidate[] }>(
    '/category-lookup/search', { keyword },
  )).data
}

export async function fetchCategoryAttributes(shopId: string, categoryId: string, title: string) {
  return (await http.post<{ categoryId: string; attributes: CategoryAttribute[] }>(
    '/category-lookup/schema', { shopId, categoryId, title },
  )).data
}

export async function fetchOriginalCategoryAttributes(categoryId: string, title: string) {
  return (await http.post<{ shopId: string; categoryId: string; attributes: CategoryAttribute[] }>(
    '/category-lookup/schema/auto', { categoryId, title },
  )).data
}
