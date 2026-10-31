import { describe, expect, it } from 'vitest'
import { buildSkuGrid } from './sku-grid'
import type { ProductEditorDraft } from './editor-contracts'

function draft(): ProductEditorDraft {
  return { title: '商品', categoryIds: [], categoryPath: '', mainImages: [], detailImages: [], attributes: [], imageDimensionId: 'color',
    dimensions: [
      { id: 'color', name: '颜色', values: [{ id: 'black', name: '黑色', sourceValueId: 'b', imageUrl: '' }, { id: 'white', name: '白色', sourceValueId: 'w', imageUrl: '' }] },
      { id: 'style', name: '款式', values: [{ id: 'long', name: '长款', sourceValueId: 'l', imageUrl: '' }, { id: 'short', name: '短款', sourceValueId: 's', imageUrl: '' }] },
    ],
    skus: [
      { id: 'one', sourceSkuId: '1234567890123456789', sourceLabel: '', specValueIds: { color: 'black', style: 'long' }, unmappedSpecIds: [], price: '19.90', stock: 3, merchantCode: '00001', state: 'active' },
      { id: 'two', sourceSkuId: null, sourceLabel: '', specValueIds: { color: 'white', style: 'short' }, unmappedSpecIds: [], price: '20.00', stock: 0, merchantCode: '', state: 'inactive' },
    ] }
}

describe('SKU 组合', () => {
  it('保留真实在售与下架状态，未采集组合不自动创建', () => {
    const result = buildSkuGrid(draft())
    expect(result.combinations).toHaveLength(4)
    expect(result.combinations.filter((item) => item.sku === null)).toHaveLength(2)
    expect(result.combinations.find((item) => item.sku?.id === 'two')?.sku?.state).toBe('inactive')
  })
  it('调整规格顺序后仍按稳定 ID 匹配，不改变编码和库存', () => {
    const data = draft()
    data.dimensions.reverse()
    const row = buildSkuGrid(data).combinations.find((item) => item.sku?.id === 'one')
    expect(row?.sku).toMatchObject({ price: '19.90', stock: 3, merchantCode: '00001' })
  })
  it('无法映射的 SKU 保留待人工处理，过多组合不会全部展开', () => {
    const data = draft()
    data.skus[0].unmappedSpecIds = ['unknown']
    expect(buildSkuGrid(data).unmatched.map((item) => item.id)).toEqual(['one'])
    expect(buildSkuGrid(data, 2).tooMany).toBe(true)
  })
})
