<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { NDatePicker, NEllipsis, NFormItem, NSpin, NTooltip, useMessage, type DataTableColumns } from 'naive-ui'
import { ProductInfoCell } from '@/entities/product'
import { PlatformDisplay } from '@/entities/platform'
import { ContextSwitchBar, DataTable, FilterBar, FilterField, FormDialog,
  ManagementListSection, PaginationBar, TableToolbar } from '@/shared/components'
import { AppButton, AppInput, AppSelect } from '@/shared/ui'
import { useProductLibrary } from '../model/useProductLibrary'
import { capturedTime, platformCode, priceRange } from '../model/format'
import { deleteProducts, exportProducts, fetchAutoPrechecks, moveProducts, queuePrechecks, resolveProductCategories } from '../api/products'
import type { LibraryProduct } from '../model/contracts'
import type { ProductRow } from '../model/nas-contracts'
import { mergePrecheck, precheckIssueCount, type AutoPrecheck, type PrecheckIssue } from '../model/precheck'
import ProductPreviewDialog from './ProductPreviewDialog.vue'
import ProductGroupManager from './ProductGroupManager.vue'

const { filters, selected, detailId, list, groups, capabilities, detail, total, refresh, reset } = useProductLibrary()
const message = useMessage()
const keyword = ref(''), capturedFrom = ref<string | null>(null), capturedTo = ref<string | null>(null)
const managerOpen = ref(false), moveOpen = ref(false), moveTarget = ref('ungrouped'), moveIds = ref<string[]>([]), busy = ref(false)
const manualOpen = ref(false), manualSeed = ref('')
const manualProduct = ref<LibraryProduct | null>(null)
const precheckRunning = ref(false)
const precheckIds = ref<string[]>([])
const precheckTargets = ref<Record<string, number>>({})
const precheckRecords = ref<Record<string, AutoPrecheck>>({})
const precheckPending = ref(new Set<string>())
const precheckRequestErrors = ref<Record<string, string>>({})
const requestedIssue = ref<PrecheckIssue | null>(null)
const rows = computed(() => list.data.value?.items ?? [])
const hasCategoryName = (path: string | null | undefined) => !!path?.trim() && !/^[\d\s→>\/\\-]+$/.test(path.trim())
const categoryKeys = computed(() => rows.value.filter((row) => row.source_platform === 'douyin' && !hasCategoryName(row.category_path))
  .map((row) => `${row.product_id}|${row.updated_at ?? ''}`))
const categories = useQuery({
  queryKey: computed(() => ['product-category-paths', categoryKeys.value] as const),
  enabled: computed(() => capabilities.data.value?.categoryLookup === true && categoryKeys.value.length > 0),
  queryFn: ({ signal, queryKey }) => resolveProductCategories(queryKey[1].map((key) => key.split('|')[0]), signal),
  staleTime: 300_000, retry: false,
  refetchInterval: (query) => !query.state.data || query.state.data.some((item) => item.status === 'unavailable') ? 60_000 : false,
})
const categoryById = computed(() => new Map((categories.data.value ?? []).map((item) => [item.productId, item])))
function categoryPath(row: ProductRow) {
  if (row.source_platform !== 'douyin') return row.category_path || '—'
  if (hasCategoryName(row.category_path)) return row.category_path
  const mapping = categoryById.value.get(row.product_id)
  if (mapping?.status === 'resolved') return mapping.path
  return categories.isFetching.value ? '类目解析中' : '类目待确认'
}
const autoIds = computed(() => [...new Set([
  ...rows.value.map((row) => row.product_id), ...precheckIds.value, ...(detailId.value ? [detailId.value] : []),
])].slice(0, 200))
const autoChecks = useQuery({
  queryKey: computed(() => ['auto-prechecks', autoIds.value] as const),
  enabled: computed(() => capabilities.data.value?.autoPrecheck === true && autoIds.value.length > 0),
  queryFn: ({ signal, queryKey }) => fetchAutoPrechecks([...queryKey[1]], signal),
  refetchInterval: 5_000, retry: false,
})
watch(() => autoChecks.data.value, (items) => {
  if (!items) return
  const next = { ...precheckRecords.value }
  for (const item of items) next[item.productId] = mergePrecheck(next[item.productId], item)
  precheckRecords.value = next
}, { immediate: true })
const autoResults = computed(() => precheckRecords.value)
const precheckCompleted = computed(() => precheckIds.value.filter((id) => {
  if (precheckRequestErrors.value[id]) return true
  const record = precheckRecords.value[id]
  const target = precheckTargets.value[id]
  return target !== undefined && !!record && record.revision >= target && (!!record.error || record.state === 'done')
}).length)
watch(precheckCompleted, (completed) => {
  if (precheckIds.value.length && completed >= precheckIds.value.length) precheckRunning.value = false
})
const groupItems = computed(() => groups.data.value ?? [])
const canWriteGroups = computed(() => capabilities.data.value?.groupWrites === true)
const preview = computed(() => {
  const product = detailId.value ? detail.data.value ?? null : null
  if (!product || product.platform !== 'douyin' || hasCategoryName(product.category)) return product
  const row = rows.value.find((item) => item.product_id === product.id)
  return row ? { ...product, category: categoryPath(row) } : product
})
const previewIndex = computed(() => rows.value.findIndex((row) => row.product_id === detailId.value))
function navigatePreview(direction: 'previous' | 'next') {
  const index = previewIndex.value + (direction === 'previous' ? -1 : 1)
  if (previewIndex.value >= 0 && rows.value[index]) detailId.value = rows.value[index].product_id
}
const groupOptions = computed(() => [
  { label: '全部分组', value: '' }, { label: '未分组', value: 'ungrouped' },
  ...groupItems.value.map((group) => ({ label: `${group.name}（${group.productCount}）`, value: group.groupId })),
])
const platformOptions = [{ label: '全部平台', value: '' }, { label: '抖音/抖店', value: 'douyin' }, { label: '拼多多', value: 'pinduoduo' }]
const viewItems = [{ key: 'all', label: '全部商品' }, { key: 'ungrouped', label: '未分组' }]
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败'

function search() {
  if (capturedFrom.value && capturedTo.value && capturedFrom.value > capturedTo.value) {
    message.error('采集开始时间不能晚于结束时间'); return
  }
  Object.assign(filters, { query: keyword.value, capturedFrom: capturedFrom.value ?? '', capturedTo: capturedTo.value ?? '', page: 1 })
  void refresh()
}

function resetFilters() {
  keyword.value = ''; capturedFrom.value = null; capturedTo.value = null; reset()
}

function openMove(ids: string[]) {
  if (!canWriteGroups.value || busy.value || !ids.length) return
  moveIds.value = [...ids]; moveTarget.value = 'ungrouped'; moveOpen.value = true
}

async function submitMove() {
  if (!canWriteGroups.value || busy.value) return
  busy.value = true
  try {
    const result = await moveProducts(moveIds.value, moveTarget.value === 'ungrouped' ? null : moveTarget.value)
    message.success(`已移动 ${result.updated.length} 个商品`); moveOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) }
  finally { busy.value = false }
}

async function download(ids: string[]) {
  if (busy.value || !ids.length) return
  busy.value = true
  try {
    const result = await exportProducts(ids)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = result.filename
    document.body.append(anchor); anchor.click(); anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
    if (result.missing) message.warning(`已导出 ${result.exported} 个商品，${result.missing} 个缺少商品数据包`)
    else message.success(`已导出 ${result.exported} 个商品`)
  } catch (error) { message.error(errorText(error)) }
  finally { busy.value = false }
}

async function removeProducts(ids: string[]) {
  if (busy.value || !ids.length || !capabilities.data.value?.productEdit) return
  if (!window.confirm(`确定删除选中的 ${ids.length} 个商品吗？`)) return
  busy.value = true
  try {
    const result = await deleteProducts(ids)
    const removed = new Set(result.deleted)
    if (detailId.value && removed.has(detailId.value)) detailId.value = null
    precheckIds.value = precheckIds.value.filter((id) => !removed.has(id))
    if (!precheckIds.value.length) precheckRunning.value = false
    message.success(`已删除 ${result.deleted.length} 个商品`)
    await refresh()
    const lastPage = Math.max(1, Math.ceil(total.value / filters.pageSize))
    if (filters.page > lastPage) filters.page = lastPage
  } catch (error) { message.error(errorText(error)) }
  finally { busy.value = false }
}

async function groupsChanged() {
  await refresh()
  if (filters.groupId && filters.groupId !== 'ungrouped' && !groupItems.value.some((group) => group.groupId === filters.groupId)) {
    filters.groupId = ''
  }
}

function openManual() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  manualSeed.value = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  const skuId = `local-${manualSeed.value}-sku`
  manualProduct.value = { id: 'manual-draft', productId: '', platform: 'douyin', title: '', groupId: null,
    groupName: null, category: null, currentPrice: null, collectedAt: '', sourceUrl: null, mainImageUrl: null,
    detailImageUrls: [], specDimensions: [], skus: [{ draftKey: skuId, sourceSkuId: null, name: '规格: 默认',
      currentPrice: null, stockLabel: null, imageUrl: null, specValues: {} }], attributes: [],
    mockEditedAt: null, packageFiles: [], history: [] }
  manualOpen.value = true
}

async function manualCreated(id: string) {
  manualOpen.value = false
  manualProduct.value = null
  void requestPrechecks([id], false)
  await refresh()
  detailId.value = id
}

function markRequestPending(ids: string[]) {
  precheckPending.value = new Set([...precheckPending.value, ...ids])
  const errors = { ...precheckRequestErrors.value }
  for (const id of ids) delete errors[id]
  precheckRequestErrors.value = errors
}

function clearRequestPending(ids: string[]) {
  const pending = new Set(precheckPending.value)
  for (const id of ids) pending.delete(id)
  precheckPending.value = pending
}

async function requestPrechecks(ids: string[], trackBatch: boolean) {
  const unique = [...new Set(ids)]
  if (!unique.length || !capabilities.data.value?.autoPrecheck) return
  markRequestPending(unique)
  if (trackBatch) {
    precheckIds.value = unique
    precheckTargets.value = {}
    precheckRunning.value = true
  }
  try {
    const response = await queuePrechecks(unique)
    const next = { ...precheckRecords.value }
    for (const item of response.items) next[item.productId] = mergePrecheck(next[item.productId], item)
    precheckRecords.value = next
    if (trackBatch) precheckTargets.value = Object.fromEntries(response.items.map((item) => [item.productId, item.revision]))
    if (response.missing.length) {
      const errors = { ...precheckRequestErrors.value }
      for (const id of response.missing) errors[id] = '商品不存在或缺少数据包'
      precheckRequestErrors.value = errors
      message.warning(`${response.missing.length} 个商品缺少可预检的数据包`)
    }
    void autoChecks.refetch()
  } catch (error) {
    const text = errorText(error)
    const errors = { ...precheckRequestErrors.value }
    for (const id of unique) errors[id] = text
    precheckRequestErrors.value = errors
    message.error(`预检请求失败：${text}；商品数据未受影响`)
  } finally {
    clearRequestPending(unique)
  }
}

function startPrecheck() {
  if (!selected.value.length || precheckRunning.value || !capabilities.data.value?.autoPrecheck) return
  void requestPrechecks([...selected.value], true)
}

function precheckView(id: string) {
  if (precheckPending.value.has(id)) return { label: '排队中', tone: 'idle', issues: [] as string[], retry: false }
  const requestError = precheckRequestErrors.value[id]
  if (requestError) return { label: '预检失败', tone: 'failed', issues: [requestError], retry: true }
  const record = autoResults.value[id]
  if (!record) return { label: '未预检', tone: 'idle', issues: [] as string[], retry: false }
  if (record.waitingForDevice) return { label: '等待预检设备', tone: 'idle', issues: [] as string[], retry: false }
  if (record.waitingForWorker) return { label: '等待设备结果', tone: 'idle', issues: [] as string[], retry: false }
  if (record.error) return { label: '预检失败', tone: 'failed', issues: [record.error], retry: true }
  if (record.state === 'pending') return { label: '排队中', tone: 'idle', issues: [] as string[], retry: false }
  if (record.state === 'running') return { label: '预检中', tone: 'running', issues: [] as string[], retry: false }
  const result = record.result
  if (!result) return { label: '预检失败', tone: 'failed', issues: ['预检结果为空'], retry: true }
  if (result.status === 'ready') return { label: '预检通过', tone: 'ready', issues: [], retry: false }
  if (result.status === 'needs_category') return { label: '待选择类目', tone: 'warning', issues: result.issues, retry: false }
  if (result.status === 'needs_completion') return {
    label: `待完善 ${precheckIssueCount(result)} 项`, tone: 'warning', issues: result.issues, retry: false,
  }
  return { label: '预检失败', tone: 'failed', issues: result.issues, retry: true }
}

function activatePrecheck(id: string) {
  const view = precheckView(id)
  if (view.retry || view.label === '未预检') { void requestPrechecks([id], false); return }
  const result = precheckRecords.value[id]?.result
  if (!result || !['needs_completion', 'needs_category'].includes(result.status)) return
  requestedIssue.value = result.issueDetails?.[0] ?? null
  detailId.value = id
}

function renderPrecheckStatus(id: string) {
  const view = precheckView(id)
  const canActivate = view.retry || view.label === '未预检' || view.tone === 'warning'
  const status = h('button', {
    type: 'button', class: ['product-library-precheck', `product-library-precheck--${view.tone}`],
    disabled: !canActivate,
    'aria-label': `${id} ${view.label}`, onClick: () => activatePrecheck(id),
  }, [view.tone === 'running' ? h(NSpin, { size: 12, strokeWidth: 18 }) : null, h('span', view.label)])
  return view.issues.length
    ? h(NTooltip, { placement: 'top-start' }, { trigger: () => status, default: () => view.issues.join('；') })
    : status
}

function productSaved(id: string) {
  requestedIssue.value = null
  void requestPrechecks([id], false)
  void refresh()
}

const columns = computed<DataTableColumns<ProductRow>>(() => [
  { type: 'selection', width: 44, fixed: 'left' },
  { title: '商品信息', key: 'title', width: 380, fixed: 'left', render: (row) => h(ProductInfoCell, {
    title: row.title, productId: row.source_product_id || row.product_id, imageUrl: row.main_image_url, density: 'compact',
  }, capabilities.data.value?.autoPrecheck ? { 'id-after': () => renderPrecheckStatus(row.product_id) } : undefined) },
  { title: '来源平台', key: 'source_platform', width: 110, align: 'center', render: (row) => {
    const code = platformCode(row.source_platform)
    return code ? h(PlatformDisplay, { code }) : (row.source_platform || '—')
  } },
  { title: '分组', key: 'group_name', width: 130, align: 'center', render: (row) => row.group_name || '未分组' },
  { title: '店铺', key: 'shop_name', width: 140, align: 'center', ellipsis: { tooltip: true } },
  { title: '类目', key: 'category_path', width: 260, align: 'center', render: (row) => h(NEllipsis, { tooltip: true, lineClamp: 2 }, () => categoryPath(row)) },
  { title: '当前价格', key: 'price', width: 120, align: 'center', render: (row) => priceRange(row) },
  { title: 'SKU', key: 'sku_count', width: 80, align: 'center' },
  { title: '采集时间', key: 'captured_at', width: 176, align: 'center', render: (row) => capturedTime(row.captured_at) },
  { title: '操作', key: 'actions', width: 170, fixed: 'right', align: 'center', render: (row) => h('div', { class: 'product-library-actions' }, [
    h(AppButton, { tone: 'link', size: 'small', onClick: () => { detailId.value = row.product_id } }, () => '编辑'),
    h(AppButton, { tone: 'link', size: 'small', disabled: busy.value, onClick: () => download([row.product_id]) }, () => '导出'),
    h(AppButton, { tone: 'link', size: 'small', disabled: busy.value || !capabilities.data.value?.productEdit,
      onClick: () => removeProducts([row.product_id]) }, () => '删除'),
  ]) },
])
</script>

<template>
  <div class="product-library-workspace">
    <ContextSwitchBar label="商品库视图" appearance="framed" :items="viewItems"
      :active-key="filters.groupId === 'ungrouped' ? 'ungrouped' : 'all'"
      @select="filters.groupId = $event === 'ungrouped' ? 'ungrouped' : ''" />
    <FilterBar density="compact">
      <FilterField width="lg">
        <AppInput v-model="keyword" placeholder="商品标题、ID、店铺或类目" aria-label="商品搜索" clearable @keyup.enter="search" />
      </FilterField>
      <FilterField width="sm"><AppSelect v-model="filters.platform" :options="platformOptions" aria-label="来源平台" /></FilterField>
      <FilterField width="sm"><AppSelect v-model="filters.groupId" :options="groupOptions" filterable label-tooltip aria-label="商品分组" /></FilterField>
      <FilterField width="md">
        <NDatePicker type="datetime" :formatted-value="capturedFrom" value-format="yyyy-MM-dd'T'HH:mm:ss"
          format="yyyy-MM-dd HH:mm:ss" placeholder="采集开始时间" clearable
          @update:formatted-value="capturedFrom = typeof $event === 'string' ? $event : null" />
      </FilterField>
      <FilterField width="md">
        <NDatePicker type="datetime" :formatted-value="capturedTo" value-format="yyyy-MM-dd'T'HH:mm:ss"
          format="yyyy-MM-dd HH:mm:ss" placeholder="采集结束时间" clearable
          @update:formatted-value="capturedTo = typeof $event === 'string' ? $event : null" />
      </FilterField>
      <template #actions><AppButton @click="resetFilters">重置</AppButton><AppButton @click="search">查询</AppButton></template>
      <template #primary-action><AppButton @click="managerOpen = true">分组管理</AppButton></template>
    </FilterBar>
    <ManagementListSection density="compact">
      <TableToolbar density="compact">
        <span v-if="selected.length">已选 {{ selected.length }} 项</span>
        <template #actions>
          <AppButton size="small" :disabled="busy || !capabilities.data.value?.productEdit" @click="openManual">手动新建商品</AppButton>
          <AppButton size="small" :disabled="!selected.length || busy" @click="download(selected)">批量导出</AppButton>
          <AppButton size="small" :disabled="!selected.length || busy || !capabilities.data.value?.productEdit" @click="removeProducts(selected)">批量删除</AppButton>
          <AppButton size="small" :disabled="!selected.length || precheckRunning || !capabilities.data.value?.autoPrecheck" @click="startPrecheck">批量预检</AppButton>
          <span v-if="precheckIds.length" class="product-library-precheck-progress">{{ precheckCompleted }}/{{ precheckIds.length }}</span>
          <AppButton size="small" :disabled="!selected.length || busy || !canWriteGroups" @click="openMove(selected)">移动分组</AppButton>
          <AppButton size="small" :disabled="busy" @click="refresh">刷新</AppButton>
        </template>
      </TableToolbar>
      <DataTable :columns="columns" :data="rows" :loading="list.isFetching.value"
        :inert="list.isFetching.value || undefined"
        :error="list.error.value ? errorText(list.error.value) : null" :row-key="(row: ProductRow) => row.product_id"
        :checked-row-keys="selected" :scroll-x="1690" viewport="fill" appearance="list" show-header-when-empty
        empty-description="暂无商品" @update:checked-row-keys="selected = $event.map(String)" @retry="refresh" />
      <PaginationBar :inert="list.isFetching.value || undefined" :page="filters.page" :page-size="filters.pageSize" :item-count="total" density="compact"
        @update:page="filters.page = $event" @update:page-size="filters.pageSize = $event; filters.page = 1" />
    </ManagementListSection>
    <ProductPreviewDialog :show="!!detailId" :product="preview" :exportable="!busy"
      :editable="capabilities.data.value?.productEdit === true" @saved="productSaved"
      :category-lookup-enabled="capabilities.data.value?.categoryLookup === true"
      :auto-result="detailId && preview?.id === detailId ? autoResults[detailId] : undefined"
      :batch-prediction="detailId && preview?.id === detailId ? autoResults[detailId]?.result?.prediction : undefined"
      :precheck-pending="!!detailId && precheckPending.has(detailId)"
      :precheck-request-error="detailId ? precheckRequestErrors[detailId] : undefined"
      :focus-issue="requestedIssue"
      :loading="detail.isFetching.value" :error="detail.error.value ? errorText(detail.error.value) : null"
      :can-previous="previewIndex > 0 && !detail.isFetching.value"
      :can-next="previewIndex >= 0 && previewIndex < rows.length - 1 && !detail.isFetching.value"
      :groupable="canWriteGroups" :navigation-items="rows.map((row) => ({ id: row.product_id, title: row.title,
        subtitle: row.source_product_id || row.product_id, imageUrl: row.main_image_url }))"
      @update:show="!$event && (detailId = null)" @navigate-to="requestedIssue = null; detailId = $event" @navigate="requestedIssue = null; navigatePreview($event)"
      @retry="detail.refetch()"
      @export="download([$event.id])" @group="openMove([$event.id])" />
    <ProductGroupManager v-model:show="managerOpen" :groups="groupItems" :writable="canWriteGroups" @changed="groupsChanged" />
    <ProductPreviewDialog :show="manualOpen" :product="manualProduct" :manual-seed="manualSeed"
      creating :editable="capabilities.data.value?.productEdit === true"
      :category-lookup-enabled="capabilities.data.value?.categoryLookup === true"
      @update:show="manualOpen = $event" @created="manualCreated" />
    <FormDialog v-model:show="moveOpen" title="移动商品分组" :submitting="busy" :submit-disabled="!canWriteGroups" @submit="submitMove">
      <NFormItem label="目标分组"><AppSelect v-model="moveTarget" :options="groupOptions.filter((item) => item.value !== '')" /></NFormItem>
    </FormDialog>
  </div>
</template>

<style scoped>
.product-library-workspace {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: var(--layout-section-gap);
}
:global(.product-library-actions) {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  white-space: nowrap;
}
:global(.product-library-precheck) { display:inline-flex; align-items:center; gap:4px; min-width:0; padding:0; border:0; background:transparent; font:inherit; white-space:nowrap; }
:global(.product-library-precheck:not(:disabled)) { cursor:pointer; }
:global(.product-library-precheck--idle) { color:var(--text-secondary); }
:global(.product-library-precheck--running) { color:var(--color-primary); }
:global(.product-library-precheck--ready) { color:var(--status-success); }
:global(.product-library-precheck--warning) { color:var(--status-warning); }
:global(.product-library-precheck--failed) { color:var(--status-danger); }
.product-library-precheck-progress { color:var(--text-secondary); font-variant-numeric:tabular-nums; }
</style>
