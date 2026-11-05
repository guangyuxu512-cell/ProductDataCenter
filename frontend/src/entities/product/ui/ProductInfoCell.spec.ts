import { mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it } from 'vitest'
import ProductInfoCell from './ProductInfoCell.vue'

describe('商品 ID 布局', () => {
  it('ID 与复制按钮组成固定组，预检状态位于独立的后置区域', () => {
    const wrapper = mount({
      components: { NMessageProvider, ProductInfoCell },
      template: `<NMessageProvider><ProductInfoCell product-id="1234567890123456789" title="商品" :image-url="null">
        <template #id-after><span class="test-status">预检中</span></template>
      </ProductInfoCell></NMessageProvider>`,
    }, {
      global: { stubs: { ProductImage: true } },
    })
    const core = wrapper.find('.product-info-cell__id-core')
    const status = wrapper.find('.product-info-cell__status')
    expect(core.find('[aria-label="复制商品ID"]').exists()).toBe(true)
    expect(core.find('.test-status').exists()).toBe(false)
    expect(status.find('.test-status').text()).toBe('预检中')
  })
})
