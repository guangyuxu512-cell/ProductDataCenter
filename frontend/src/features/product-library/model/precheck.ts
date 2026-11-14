import type { PredictedCategory } from '../api/category-lookup'

export interface CategoryPrediction {
  status: 'missing_data' | 'no_recommendation' | 'needs_category_confirmation' | 'recommended'
  sourceVersion: string
  missing: string[]
  shopId: string | null
  candidates: PredictedCategory[]
  recommendedId: string | null
}

export type PrecheckStatus = 'ready' | 'needs_completion' | 'needs_category' | 'failed'
export interface PrecheckIssue {
  code: string
  message: string
  tab: 'base' | 'images' | 'attributes' | 'sku'
  fieldId?: string
  skuIndex?: number
  skuId?: string
}
export interface PrecheckResult {
  productId: string
  title: string
  status: PrecheckStatus
  issues: string[]
  issueDetails?: PrecheckIssue[]
  prediction?: CategoryPrediction
}
export interface AutoPrecheck {
  productId: string
  revision: number
  state: 'pending' | 'running' | 'done'
  result: PrecheckResult | null
  error: string | null
  waitingForWorker?: boolean
  waitingForDevice?: boolean
  updatedAt: string
}

/** Keep a late response for an older queue revision from replacing newer UI state. */
export function mergePrecheck(current: AutoPrecheck | undefined, incoming: AutoPrecheck): AutoPrecheck {
  if (!current || incoming.revision > current.revision) return incoming
  if (incoming.revision < current.revision) return current
  return Date.parse(incoming.updatedAt) >= Date.parse(current.updatedAt) ? incoming : current
}

export function precheckIssueCount(result: PrecheckResult | null | undefined): number {
  return result?.issueDetails?.length ?? result?.issues.length ?? 0
}
