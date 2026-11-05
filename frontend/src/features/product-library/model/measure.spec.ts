import { describe, expect, it } from 'vitest'
import type { MeasureTemplate } from '../api/category-lookup'
import { formatMeasure, parseMeasure, validMeasure } from './measure'

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
