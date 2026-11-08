import { describe, expect, it } from 'vitest'
import { orderSkuRows, skuGroupRowSpans } from './sku-order'

const groups = [
  { values: [{ id: 'black' }, { id: 'leopard' }] },
  { values: [{ id: '35' }, { id: '36' }, { id: '37' }] },
]

describe('SKU 表格排序', () => {
  it('按规格值顺序整理稀疏组合，不改变原数组或各行信息', () => {
    const rows = [
      { skuId: 'c', specIds: ['leopard', '37'], price: '33' },
      { skuId: 'a', specIds: ['black', '36'], price: '11' },
      { skuId: 'd', specIds: ['leopard', '35'], price: '44' },
      { skuId: 'b', specIds: ['black', '35'], price: '22' },
    ]
    const sorted = orderSkuRows(rows, groups)
    expect(sorted.map((row) => [row.skuId, row.price])).toEqual([
      ['b', '22'], ['a', '11'], ['d', '44'], ['c', '33'],
    ])
    expect(rows.map((row) => row.skuId)).toEqual(['c', 'a', 'd', 'b'])
    expect(sorted[0]).toBe(rows[3])
  })

  it('规格图所在维度置前时随展示顺序排序', () => {
    const rows = [{ specIds: ['leopard', '35'] }, { specIds: ['black', '36'] }, { specIds: ['black', '35'] }]
    expect(orderSkuRows(rows, groups, 1)).toEqual([rows[2], rows[0], rows[1]])
  })

  it('规格 ID 无法唯一匹配时保留原顺序，不猜测组合', () => {
    const rows = [{ specIds: ['leopard', '37'] }, { specIds: ['unknown', '35'] }]
    expect(orderSkuRows(rows, groups)).toEqual(rows)
    expect(orderSkuRows(rows, [{ values: [{ id: 'leopard' }, { id: 'leopard' }] }, groups[1]])).toEqual(rows)
  })

  it('只合并相邻且规格 ID 相同的首列单元格', () => {
    const rows = [{ specIds: ['black', '35'] }, { specIds: ['black', '36'] },
      { specIds: ['leopard', '35'] }, { specIds: ['leopard', '37'] }, { specIds: ['other', '35'] }]
    expect(skuGroupRowSpans(rows, 0)).toEqual([2, 1, 2, 1, 1])
    expect(skuGroupRowSpans(rows, 2)).toEqual([1, 1, 1, 1, 1])
  })
})
