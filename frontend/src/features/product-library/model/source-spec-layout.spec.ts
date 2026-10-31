import { describe, expect, it } from 'vitest'
import type { ProductSku } from './contracts'
import { sourceSpecLayout } from './source-spec-layout'

function sku(id: string, name: string): ProductSku {
  return { draftKey: id, sourceSkuId: id, name, currentPrice: null, stockLabel: null, imageUrl: null, specValues: {} }
}

describe('来源规格展示', () => {
  it('按真实来源名称展示维度与组合，不补造缺失组合', () => {
    const result = sourceSpecLayout([
      sku('1', '颜色（2）：黑色 / 款式：长款'),
      sku('2', '颜色（2）：黑色 / 款式：短款/加厚'),
      sku('3', '颜色（2）：白色 / 款式：长款'),
    ])!
    expect(result.axes).toEqual([{ name: '颜色', values: ['黑色', '白色'] }, { name: '款式', values: ['长款', '短款/加厚'] }])
    expect(result.rows).toEqual({ '1': ['黑色', '长款'], '2': ['黑色', '短款/加厚'], '3': ['白色', '长款'] })
  })

  it('来源格式不一致时保留原始规格，不猜测映射', () => {
    expect(sourceSpecLayout([sku('1', '颜色：黑色 / 款式：长款'), sku('2', '白色')])).toBeNull()
    expect(sourceSpecLayout([sku('1', '颜色：黑色 / 颜色：白色')])).toBeNull()
  })
})
