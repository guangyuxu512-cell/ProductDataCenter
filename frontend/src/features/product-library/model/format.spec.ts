import { describe, expect, it } from 'vitest'
import { capturedTime, detailView, platformCode, productTitleLength } from './format'
import { productListParams } from '../api/products'
import type { NasDetail } from './nas-contracts'

describe('采集字段适配', () => {
  it('标题计数与已确认的抖店页面一致', () => {
    expect(productTitleLength('商'.repeat(30))).toBe(60)
    expect(productTitleLength('商'.repeat(30) + 'A')).toBe(61)
  })
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
})
