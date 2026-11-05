import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { MeasureTemplate } from '../api/category-lookup'
import ProductMeasureInput from './ProductMeasureInput.vue'

const template: MeasureTemplate = { id: '53', name: '三段尺寸', modules: [48, 49, 50].map((id, index) => ({
  id: String(id), prefix: '', suffix: index < 2 ? '*' : '', required: true, requiredTips: '该项为必填，请输入',
  placeholder: '请输入', units: index === 2 ? [{ label: 'cm', value: '39' }, { label: 'm', value: '41' }] : [],
  dataType: 'float', minimum: 1, maximum: 10000, precision: 1,
})) }

describe('度量属性输入', () => {
  it('已有值分段回填，修改后生成平台格式', async () => {
    const wrapper = mount(ProductMeasureInput, { props: { modelValue: '11*22*22cm',
      templates: [template], disabled: false, label: '规格尺寸' } })
    const inputs = wrapper.findAll('input').filter((input) => input.attributes('aria-label')?.startsWith('规格尺寸 '))
    expect(inputs.map((input) => (input.element as HTMLInputElement).value).slice(0, 3)).toEqual(['11', '22', '22'])
    await inputs[1].setValue('33')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['11*33*22cm'])
  })
  it('无法按模板拆分的原值仍然显示', () => {
    const wrapper = mount(ProductMeasureInput, { props: { modelValue: '见实物',
      templates: [template], disabled: false, label: '规格尺寸' } })
    expect(wrapper.find('input[aria-label="规格尺寸"]').element).toHaveProperty('value', '见实物')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
