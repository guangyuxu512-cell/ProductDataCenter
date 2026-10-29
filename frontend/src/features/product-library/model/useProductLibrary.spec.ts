import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useProductLibrary } from './useProductLibrary'
import * as api from '../api/products'
import type { ProductListResponse } from './nas-contracts'

vi.mock('../api/products', () => ({
  fetchProducts: vi.fn(), fetchGroups: vi.fn(), fetchCapabilities: vi.fn(), fetchDetail: vi.fn(),
}))

function page(total: number | null, id = '3760269504500859111'): ProductListResponse {
  return { items: [{ product_id: id } as ProductListResponse['items'][number]], total, totalIncluded: total !== null, limit: 20, offset: 0 }
}

const wrappers: ReturnType<typeof mount>[] = []
function setup() {
  let state!: ReturnType<typeof useProductLibrary>
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } } })
  const wrapper = mount(defineComponent({ setup() { state = useProductLibrary(); return () => h('div') } }), {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  wrappers.push(wrapper)
  return state
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.fetchProducts).mockResolvedValue(page(60))
  vi.mocked(api.fetchGroups).mockResolvedValue([])
  vi.mocked(api.fetchCapabilities).mockResolvedValue({ groupWrites: true, export: true, productEdit: false, importProducts: false })
})
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

describe('商品查询缓存与竞态', () => {
  it('首次统计，翻页复用总数，筛选变更重算并清除选择和详情', async () => {
    const state = setup(); await flushPromises()
    expect(api.fetchProducts).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }), true, expect.any(AbortSignal))
    state.selected.value = ['3760269504500859111']
    vi.mocked(api.fetchProducts).mockResolvedValue(page(null))
    state.filters.page = 2; await nextTick(); await flushPromises()
    expect(api.fetchProducts).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }), false, expect.any(AbortSignal))
    expect(state.total.value).toBe(60); expect(state.selected.value).toEqual([])
    state.selected.value = ['3760269504500859111']; state.detailId.value = 'old'
    vi.mocked(api.fetchProducts).mockResolvedValue(page(2))
    state.filters.platform = 'pinduoduo'; await nextTick(); await flushPromises()
    expect(state.filters.page).toBe(1); expect(state.detailId.value).toBeNull()
    expect(state.selected.value).toEqual([])
    expect(api.fetchProducts).toHaveBeenLastCalledWith(expect.objectContaining({ platform: 'pinduoduo', page: 1 }), true, expect.any(AbortSignal))
  })

  it('旧请求延迟返回不会覆盖新筛选或总数', async () => {
    let resolveOld!: (value: ProductListResponse) => void
    vi.mocked(api.fetchProducts).mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve }))
    const state = setup(); await flushPromises()
    vi.mocked(api.fetchProducts).mockResolvedValue(page(1, 'pdd:3837817973876326524'))
    state.filters.platform = 'pinduoduo'; await nextTick(); await flushPromises()
    resolveOld(page(999)); await flushPromises()
    expect(state.total.value).toBe(1)
    expect(state.list.data.value?.items[0]?.product_id).toBe('pdd:3837817973876326524')
  })

  it('返回已访问的筛选时重新统计新增商品，翻页仍复用本轮总数', async () => {
    let currentTotal = 60
    vi.mocked(api.fetchProducts).mockImplementation(async (filters, includeTotal) =>
      page(includeTotal ? (filters.platform === 'pinduoduo' ? 10 : currentTotal) : null))
    const state = setup(); await flushPromises()
    expect(state.total.value).toBe(60)
    state.filters.platform = 'pinduoduo'; await nextTick(); await flushPromises()
    expect(state.total.value).toBe(10)

    currentTotal = 85
    state.filters.platform = ''; await nextTick(); await flushPromises()
    expect(api.fetchProducts).toHaveBeenLastCalledWith(expect.objectContaining({ platform: '', page: 1 }), true, expect.any(AbortSignal))
    expect(state.total.value).toBe(85)

    state.filters.page = 2; await nextTick(); await flushPromises()
    expect(api.fetchProducts).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }), false, expect.any(AbortSignal))
    expect(state.total.value).toBe(85)
  })

  it('手动刷新重新统计，不使用三秒商品轮询', async () => {
    const state = setup(); await flushPromises()
    vi.mocked(api.fetchProducts).mockClear()
    await state.refresh(); await flushPromises()
    expect(api.fetchProducts).toHaveBeenCalledTimes(1)
    expect(api.fetchProducts).toHaveBeenLastCalledWith(expect.any(Object), true, expect.any(AbortSignal))
  })
})
