import { computed, reactive, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { fetchCapabilities, fetchDetail, fetchGroups, fetchProducts } from '../api/products'
import type { ProductFilters } from './nas-contracts'
import { detailView } from './format'

export function useProductLibrary() {
  const client = useQueryClient()
  const filters = reactive<ProductFilters>({ query: '', platform: '', groupId: '', capturedFrom: '', capturedTo: '', page: 1, pageSize: 20 })
  const selected = ref<string[]>([])
  const detailId = ref<string | null>(null)
  const counts = reactive(new Map<string, number>())
  const filterKey = computed(() => JSON.stringify([filters.query.trim(), filters.platform, filters.groupId, filters.capturedFrom, filters.capturedTo]))
  const list = useQuery({
    queryKey: computed(() => ['products', filterKey.value, filters.page, filters.pageSize] as const),
    queryFn: async ({ signal, queryKey }) => {
      const [, current, page, pageSize] = queryKey
      const [query, platform, groupId, capturedFrom, capturedTo] = JSON.parse(current) as [string, ProductFilters['platform'], string, string, string]
      const response = await fetchProducts({ query, platform, groupId, capturedFrom, capturedTo, page, pageSize }, !counts.has(current), signal)
      if (!signal.aborted && current === filterKey.value && response.totalIncluded && response.total !== null) {
        counts.set(current, response.total)
      }
      return response
    },
    staleTime: 0,
  })
  const groups = useQuery({ queryKey: ['product-groups'], queryFn: ({ signal }) => fetchGroups(signal) })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: ({ signal }) => fetchCapabilities(signal) })
  const detail = useQuery({
    queryKey: computed(() => ['product-detail', detailId.value] as const),
    enabled: computed(() => detailId.value !== null),
    queryFn: ({ signal, queryKey }) => fetchDetail(queryKey[1]!, signal),
    select: detailView,
    staleTime: 0,
  })
  watch(filterKey, () => {
    counts.clear()
    filters.page = 1; selected.value = []; detailId.value = null
  }, { flush: 'sync' })
  watch(() => [filters.page, filters.pageSize], () => { selected.value = []; detailId.value = null }, { flush: 'sync' })

  async function refresh() {
    counts.clear()
    selected.value = []
    await Promise.all([
      client.invalidateQueries({ queryKey: ['products'] }),
      client.invalidateQueries({ queryKey: ['product-groups'] }),
      client.invalidateQueries({ queryKey: ['product-detail'] }),
    ])
  }

  function reset() {
    Object.assign(filters, { query: '', platform: '', groupId: '', capturedFrom: '', capturedTo: '', page: 1 })
  }

  return { filters, selected, detailId, list, groups, capabilities, detail,
    total: computed(() => list.data.value?.total ?? counts.get(filterKey.value) ?? 0), refresh, reset }
}
