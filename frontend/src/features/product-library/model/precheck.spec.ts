import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchOriginalCategoryAttributes, predictProductCategory } from '../api/category-lookup'
import { fetchDetail } from '../api/products'
import type { NasDetail } from './nas-contracts'
import { batchPrecheck, precheckProduct, type PrecheckResult } from './precheck'

vi.mock('../api/category-lookup', () => ({ fetchOriginalCategoryAttributes: vi.fn(), predictProductCategory: vi.fn() }))
vi.mock('../api/products', () => ({ fetchDetail: vi.fn() }))

function detail(id: string, platform = 'douyin'): NasDetail {
  return {
    product: { product_id: id, source_product_id: id, source_platform: platform, title: '完整标题', title_status: '',
      group_id: null, group_name: null, shop_name: '', category_level_4: '', category_path: '',
      current_price_min: '19.99', current_price_max: '19.99', sku_count: 1, main_image_count: 1, detail_image_count: 0,
      sku_image_count: 0, main_image_url: 'https://example.test/main.png', asset_rel_path: '', workbook_rel_path: '',
      raw_rel_path: '', captured_at: null, updated_at: null },
    sourceCategoryId: platform === 'douyin' ? '100' : null,
    sourceAttributes: [{ id: '1', name: '材质', values: ['棉'] }], targetCategory: [], targetAttributes: [],
    skus: [{ sku_id: 's1', sku_name: '默认', current_price: '19.99', image_rel_path: '', sort_order: 0 }], images: [],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchDetail).mockImplementation(async (id) => detail(id))
  vi.mocked(fetchOriginalCategoryAttributes).mockResolvedValue({ shopId: 'shop', categoryId: '100', attributes: [
    { id: '1', label: '材质', required: true, options: [] },
    { id: '2', label: '品牌', required: true, options: [] },
  ] })
})

describe('商品批量预检', () => {
  it('抖音使用原类目，列出没有填写的必填属性', async () => {
    const result = await precheckProduct('12345678')
    expect(result.status).toBe('needs_completion')
    expect(result.issues).toEqual(['必填属性：品牌'])
    expect(fetchOriginalCategoryAttributes).toHaveBeenCalledWith('100', '完整标题')
    expect(predictProductCategory).not.toHaveBeenCalled()
  })

  it('拼多多保留平台候选并提示选择抖店类目', async () => {
    vi.mocked(fetchDetail).mockResolvedValue(detail('pdd:12345678', 'pinduoduo'))
    vi.mocked(predictProductCategory).mockResolvedValue({ status: 'needs_category_confirmation', sourceVersion: 'a'.repeat(64),
      missing: [], shopId: 'shop', recommendedId: null, candidates: [
        { id: '101', name: '收纳架', path: '居家 → 收纳架', levels: [{ id: '100', name: '居家' }, { id: '101', name: '收纳架' }], selectable: true },
      ] })
    const result = await precheckProduct('pdd:12345678')
    expect(result.status).toBe('needs_category')
    expect(result.prediction?.candidates[0].id).toBe('101')
    expect(fetchOriginalCategoryAttributes).not.toHaveBeenCalled()
  })

  it('限制并发、复用同一类目属性并记录单个商品失败', async () => {
    let active = 0, highest = 0
    vi.mocked(fetchDetail).mockImplementation(async (id) => {
      active++; highest = Math.max(highest, active)
      await new Promise((resolve) => setTimeout(resolve, 5))
      active--
      if (id === '3') throw new Error('商品不存在')
      return detail(id)
    })
    const results: PrecheckResult[] = []
    await batchPrecheck(['1', '2', '3', '4', '5'], (result) => results.push(result), 2)
    expect(highest).toBeLessThanOrEqual(2)
    expect(fetchOriginalCategoryAttributes).toHaveBeenCalledTimes(1)
    expect(results.find((item) => item.productId === '3')).toMatchObject({ status: 'failed', issues: ['商品不存在'] })
    expect(results).toHaveLength(5)
  })
})
