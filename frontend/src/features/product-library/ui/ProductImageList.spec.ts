import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ProductImageList from './ProductImageList.vue'

const items = [
  { key: 'a', src: 'https://example.test/a.png', label: '图片 A', canLocal: true, canDelete: true },
  { key: 'b', src: 'https://example.test/b.png', label: '图片 B', canLocal: true, canDelete: true },
]

describe('商品图片共享列表', () => {
  it('主图和详情图使用同一拖拽事件，且不再出现上移下移按钮', async () => {
    const wrapper = mount(ProductImageList, { props: { items, editable: true, draggable: true } })
    const cards = wrapper.findAll('.product-image-list__card')
    await cards[0].trigger('dragstart')
    await cards[1].trigger('dragover')
    await cards[1].trigger('drop')
    expect(wrapper.emitted('reorder')).toEqual([[0, 1]])
    expect(wrapper.text()).not.toContain('上移')
    expect(wrapper.text()).not.toContain('下移')
  })

  it('拖动结束的点击不会误开预览，SKU 模式可关闭拖拽以保持绑定', async () => {
    vi.useFakeTimers()
    const wrapper = mount(ProductImageList, { props: { items, editable: true, draggable: true } })
    const first = wrapper.find('.product-image-list__card')
    await first.trigger('dragstart')
    await first.trigger('dragend')
    await wrapper.find('.n-image').trigger('click')
    expect(wrapper.emitted('preview')).toBeUndefined()
    vi.runAllTimers()
    await wrapper.find('.n-image').trigger('click')
    expect(wrapper.emitted('preview')).toEqual([['https://example.test/a.png']])
    await wrapper.setProps({ draggable: false })
    expect(wrapper.find('.product-image-list__card').attributes('draggable')).toBe('false')
    vi.useRealTimers()
  })
})
