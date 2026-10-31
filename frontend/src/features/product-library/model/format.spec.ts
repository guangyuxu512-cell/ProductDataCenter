import { describe, expect, it } from 'vitest'
import { capturedTime, detailView, platformCode } from './format'
import { productListParams } from '../api/products'
import type { NasDetail } from './nas-contracts'

describe('采集字段适配', () => {
  it('19 位 ID 保持字符串，精确检索保留分页与秒级参数', () => {
    const params = productListParams({ query: '3760269504500859111', platform: '', groupId: '',
      capturedFrom: '2026-10-26T08:18:34', capturedTo: '2026-10-26T08:18:34', page: 2, pageSize: 20 }, false)
    expect(params.productId).toBe('3760269504500859111')
    expect(params.offset).toBe(20)
    expect(params.capturedToTime).toBe('2026-10-26T08:18:34')
    expect(params.includeTotal).toBe(false)
  })
  it('统一显示北京时间到秒，平台代码明确映射', () => {
    expect(capturedTime('2026-10-26T00:18:34.999999Z')).toBe('2026-10-26 08:18:34')
    expect(capturedTime(null)).toBe('—')
    expect(platformCode('pinduoduo')).toBe('pdd')
    expect(platformCode('unknown')).toBeNull()
  })
  it('不把未知平台伪装成抖音', () => {
    expect(() => detailView({ product: { source_platform: 'unknown' } } as NasDetail)).toThrow('暂不支持')
  })
  it('规格图独立展示，不按顺序猜测 SKU 图归属', () => {
    const detail = {
      product: { product_id: '1', source_platform: 'douyin', source_product_id: '1', title: '商品',
        group_id: null, group_name: null, category_path: '', current_price_min: null, current_price_max: null,
        main_image_url: null, captured_at: null },
      skus: [
        { sku_id: 'a', sku_name: '黑色', image_rel_path: '', sort_order: 0, current_price: null },
        { sku_id: 'b', sku_name: '白色', image_rel_path: 'white.jpg', sort_order: 1, current_price: null },
      ],
      images: [
        { image_type: 'sku', sort_order: 0, rel_path: 'white.jpg', source_url: 'https://example.test/white.jpg' },
        { image_type: 'sku', sort_order: 1, rel_path: '', source_url: 'https://example.test/other.jpg' },
      ],
    } as NasDetail
    const view = detailView(detail)
    expect(view.previewSkuImageUrls).toEqual(['https://example.test/white.jpg', 'https://example.test/other.jpg'])
    expect(view.skus[0].imageUrl).toBeNull()
    expect(view.skus[1].imageUrl).toBe('https://example.test/white.jpg')
  })
})
