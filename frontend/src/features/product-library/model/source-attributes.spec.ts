import { describe, expect, it } from 'vitest'
import type { CategoryAttribute } from '../api/category-lookup'
import type { LibraryProduct } from './contracts'
import { originalAttributeValue, pddAttributeValue } from './source-attributes'

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

describe('拼多多来源属性匹配', () => {
  const pdd = { platform: 'pdd', attributes: [
    { id: '482', name: '产地', value: '中国大陆' },
    { id: '501', name: '材质', value: '玻璃' },
  ] } as LibraryProduct
  const origin: CategoryAttribute = { id: 'target-9', label: '产地', required: false,
    options: [{ label: '中国大陆', value: 'target-option' }] }
  it('按唯一名称和抖店选项的值匹配，不沿用拼多多 ID', () => {
    expect(pddAttributeValue(origin, [origin], pdd)).toBe('中国大陆')
  })
  it('名称重复、选项不接受或值不唯一时留空', () => {
    expect(pddAttributeValue(origin, [origin, { ...origin, id: 'other' }], pdd)).toBe('')
    expect(pddAttributeValue({ ...origin, options: [{ label: '其他', value: '1' }] }, [origin], pdd)).toBe('')
    expect(pddAttributeValue({ ...origin, options: [...origin.options, ...origin.options] }, [origin], pdd)).toBe('')
    expect(pddAttributeValue(origin, [origin], { ...pdd, attributes: [...pdd.attributes, pdd.attributes[0]] })).toBe('')
  })
  it('无选项的文本字段也能匹配；不会对抖音来源调用跨平台映射', () => {
    const material = { ...origin, label: '材质', options: [] }
    expect(pddAttributeValue(material, [material], pdd)).toBe('玻璃')
    expect(pddAttributeValue(material, [material], { ...pdd, platform: 'douyin' })).toBe('')
  })
})
