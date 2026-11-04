import { http } from '@/shared/api/http-client'

export interface CategoryCandidate { id: string; name: string; path: string }
export interface CategoryAttribute {
  id: string
  label: string
  required: boolean
  options: Array<{ label: string; value: string }>
  control: 'single' | 'multi' | 'text' | 'number'
  allowCustom: boolean
}
export interface CategoryTreeItem { id: string; name: string; isLeaf: boolean; enabled: boolean }
export interface PredictedCategory extends CategoryCandidate {
  levels: Array<{ id: string; name: string }>
  selectable: boolean | null
}

interface PredictionResult {
    status: 'missing_data' | 'no_recommendation' | 'needs_category_confirmation' | 'recommended'
    sourceVersion: string
    missing: string[]
    shopId: string | null
    candidates: PredictedCategory[]
    recommendedId: string | null
}

export async function predictProductCategory(productId: string) {
  return (await http.post<PredictionResult>('/category-lookup/predict', { productId })).data
}

export async function predictManualCategory(title: string, imageUrl: string) {
  return (await http.post<PredictionResult>('/category-lookup/predict/manual', { title, imageUrl })).data
}

export async function fetchCategoryTree(parentId = '0', shopId: string | null = null, refresh = false) {
  return (await http.post<{ shopId: string; parentId: string; items: CategoryTreeItem[]; fromCache: boolean }>(
    '/category-lookup/tree', { parentId, shopId, refresh },
  )).data
}

export async function searchCategoryCandidates(keyword: string) {
  return (await http.post<{ shopId: string; candidates: CategoryCandidate[] }>(
    '/category-lookup/search', { keyword },
  )).data
}

export async function fetchCategoryAttributes(shopId: string, categoryId: string, title: string, refresh = false) {
  return (await http.post<{ categoryId: string; attributes: CategoryAttribute[] }>(
    '/category-lookup/schema', { shopId, categoryId, title, refresh },
  )).data
}

export async function fetchOriginalCategoryAttributes(categoryId: string, title: string, refresh = false) {
  return (await http.post<{ shopId: string; categoryId: string; attributes: CategoryAttribute[] }>(
    '/category-lookup/schema/auto', { categoryId, title, refresh },
  )).data
}
