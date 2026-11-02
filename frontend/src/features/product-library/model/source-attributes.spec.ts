import { describe, expect, it } from 'vitest'
import type { CategoryAttribute } from '../api/category-lookup'
import type { LibraryProduct } from './contracts'
import { originalAttributeValue } from './source-attributes'

const target: CategoryAttribute = { id: '501', label: '材质', required: true, options: [] }
const product = { platform: 'douyin', sourceCategoryId: '100', attributes: [
  { id: '501', name: '材质旧名称', value: '304 不锈钢' },
  { id: '502', name: '适用场景', value: '家用、户外' },
] } as LibraryProduct

describe('原抖店类目属性回显', () => {
  it('原类目优先按属性 ID 回显，名称一致时可匹配没有 ID 的属性', () => {
    expect(originalAttributeValue(target, [target], product, '100')).toBe('304 不锈钢')
    const named = { ...target, id: 'other', label: '适用场景' }
    expect(originalAttributeValue(named, [named], product, '100')).toBe('家用、户外')
  })
  it('更换类目或不同平台不把来源属性当成已匹配', () => {
    expect(originalAttributeValue(target, [target], product, '200')).toBe('')
    expect(originalAttributeValue(target, [target], { ...product, platform: 'pdd' }, '100')).toBe('')
  })
  it('同名或同 ID 来源不唯一时留空', () => {
    const duplicate = { ...product, attributes: [
      { id: '1', name: '材质', value: '棉' }, { id: '2', name: '材质', value: '麻' },
    ] }
    expect(originalAttributeValue(target, [target], duplicate, '100')).toBe('')
    expect(originalAttributeValue(target, [target, { ...target, id: '2' }], duplicate, '100')).toBe('')
  })
})
