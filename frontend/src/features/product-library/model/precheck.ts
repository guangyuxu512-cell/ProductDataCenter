import { fetchOriginalCategoryAttributes, predictProductCategory } from '../api/category-lookup'
import { fetchDetail } from '../api/products'
import { detailView } from './format'
import { originalAttributeValue, pddAttributeValue } from './source-attributes'

export type CategoryPrediction = Awaited<ReturnType<typeof predictProductCategory>>
export type PrecheckStatus = 'ready' | 'needs_completion' | 'needs_category' | 'failed'
export interface PrecheckResult {
  productId: string
  title: string
  status: PrecheckStatus
  issues: string[]
  prediction?: CategoryPrediction
}
export interface AutoPrecheck {
  productId: string
  state: 'pending' | 'running' | 'done'
  result: PrecheckResult | null
  error: string | null
  updatedAt: string
}

/** Check only information available in the saved package and category schema. */
export async function precheckProduct(
  productId: string, schemaLookup = fetchOriginalCategoryAttributes,
): Promise<PrecheckResult> {
  const product = detailView(await fetchDetail(productId))
  const issues: string[] = []
  if (!product.title.trim()) issues.push('商品标题')
  if (!product.mainImageUrl) issues.push('商品主图')
  if (!product.skus.length) issues.push('SKU 规格')
  else if (product.skus.some((sku) => !sku.currentPrice || Number(sku.currentPrice) <= 0)) issues.push('SKU 价格')
  if (product.platform === 'pdd' && !product.targetCategory?.length) {
    const prediction = await predictProductCategory(productId)
    for (const value of prediction.missing) if (!issues.includes(value)) issues.push(value)
    if (!issues.length) issues.push(prediction.candidates.length ? '待确认抖店类目' : '未找到推荐类目，请手动选择')
    return { productId, title: product.title, status: prediction.missing.length ? 'needs_completion' : 'needs_category', issues, prediction }
  }
  const categoryId = product.platform === 'douyin'
    ? product.sourceCategoryId : product.platform === 'pdd' ? product.targetCategory?.at(-1)?.id : null
  if (!categoryId) {
    issues.push('抖店类目')
    return { productId, title: product.title, status: 'needs_category', issues }
  }
  const { attributes } = await schemaLookup(categoryId, product.title)
  const missing = attributes.filter((field) => {
    if (!field.required) return false
    if (product.platform === 'douyin') return !originalAttributeValue(field, attributes, product, categoryId).trim()
    const saved = product.targetAttributes?.find((item) => item.id === field.id)
    const value = saved ? saved.values.join('、') : pddAttributeValue(field, attributes, product)
    return !value.trim()
  }).map((field) => field.label)
  if (missing.length) issues.push(`必填属性：${missing.join('、')}`)
  return { productId, title: product.title, status: issues.length ? 'needs_completion' : 'ready', issues }
}

/** The backend applies its own per-shop limit; this caps total browser requests. */
export async function batchPrecheck(
  productIds: string[], onResult: (result: PrecheckResult) => void, concurrency = 15,
): Promise<void> {
  let next = 0
  const schemas = new Map<string, ReturnType<typeof fetchOriginalCategoryAttributes>>()
  const schemaLookup: typeof fetchOriginalCategoryAttributes = (categoryId, title, refresh = false) => {
    if (!schemas.has(categoryId)) schemas.set(categoryId, fetchOriginalCategoryAttributes(categoryId, title, refresh))
    return schemas.get(categoryId)!
  }
  const run = async () => {
    while (next < productIds.length) {
      const productId = productIds[next++]
      try { onResult(await precheckProduct(productId, schemaLookup)) }
      catch (error) {
        onResult({ productId, title: '', status: 'failed', issues: [error instanceof Error ? error.message : '预检失败'] })
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(Math.max(1, concurrency), productIds.length) }, run))
}
