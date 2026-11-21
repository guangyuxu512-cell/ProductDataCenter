import { describe, expect, it } from 'vitest'
import type { MeasureTemplate } from '../api/category-lookup'
import { fabricCompositionProblem, formatMeasure, parseMeasure, parseMultiMeasure, validMeasure, validMultiMeasure } from './measure'

// Sanitized measure template from category 1000001535's getSchema response.
const template: MeasureTemplate = { id: '53', name: '三脚架长宽高度量衡模板', modules: [48, 49, 50].map((id, index) => ({
  id: String(id), prefix: '', suffix: index < 2 ? '*' : '', required: true, requiredTips: '该项为必填，请输入',
  placeholder: '请输入', units: index === 2 ? [{ label: 'cm', value: '39' }, { label: 'm', value: '41' },
    { label: 'mm', value: '90' }] : [], dataType: 'float', minimum: 1, maximum: 10000, precision: 1,
})) }

describe('按平台度量模板处理尺寸', () => {
  it('将三段和单位合并并能再次拆开', () => {
    const parts = [{ value: '11', unit: '' }, { value: '22', unit: '' }, { value: '22', unit: 'cm' }]
    expect(formatMeasure(template, parts)).toBe('11*22*22cm')
    expect(parseMeasure(template, '11*22*22cm')).toEqual(parts)
    expect(validMeasure(template, '11*22*22cm')).toBe(true)
  })
  it('按真实范围、精度、必填和单位校验，不接受不支持的原值', () => {
    for (const value of ['0*22*22cm', '11.22*22*22cm', '11*22*10001cm', '11*22*22', '见实物']) {
      expect(validMeasure(template, value)).toBe(false)
    }
  })
})

it('依据真实复合多值规则检查材质和百分比', () => {
  const rule = { units: [{ label: '%', value: '15' }], minimum: 0.01, maximum: 100, precision: 2, dataType: 'float' as const }
  const options = [{ label: '聚酯纤维', value: '5673' }]
  expect(validMultiMeasure(rule, '聚酯纤维100%', options)).toBe(true)
  expect(validMultiMeasure(rule, '棉20%')).toBe(true)
  for (const value of ['聚酯纤维', '100%', '聚酯纤维0%', '聚酯纤维100.01%', '聚酯纤维1.234%']) {
    expect(validMultiMeasure(rule, value, options)).toBe(false)
  }
  expect(validMultiMeasure(rule, '自定义99%', options)).toBeNull()
  expect(parseMultiMeasure(rule, '聚酯纤维100%', options)).toEqual({ name: '聚酯纤维', value: '100', unit: '%' })
  expect(parseMultiMeasure(rule, '聚酯纤维100%', [])).toEqual({ name: '聚酯纤维', value: '100', unit: '%' })
  expect(parseMultiMeasure(rule, '棉20%', options)).toEqual({ name: '棉', value: '20', unit: '%' })
  expect(parseMultiMeasure(rule, '自定义99%', options)).toBeNull()
  expect(parseMultiMeasure(rule, '原始未知值', options)).toBeNull()
  expect(fabricCompositionProblem(rule, ['聚酯纤维80%', '棉20%'], options)).toBeNull()
  expect(fabricCompositionProblem(rule, ['聚酯纤维80%', '棉10%'], options)).toBe('含量总和需为100%')
  expect(fabricCompositionProblem(rule, ['棉50%', '棉50%'], options)).toBe('不可重复')
  expect(fabricCompositionProblem(rule, ['自定义99%'], options)).toBeNull()
})
