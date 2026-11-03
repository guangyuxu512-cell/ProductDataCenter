<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { NDatePicker, NEllipsis, NFormItem, useMessage, type DataTableColumns } from 'naive-ui'
import { ProductInfoCell } from '@/entities/product'
import { PlatformDisplay } from '@/entities/platform'
import { ContextSwitchBar, DataTable, FilterBar, FilterField, FormDialog,
  ManagementListSection, PaginationBar, TableToolbar } from '@/shared/components'
import { AppButton, AppDialog, AppInput, AppSelect } from '@/shared/ui'
import { useProductLibrary } from '../model/useProductLibrary'
import { capturedTime, platformCode, priceRange } from '../model/format'
import { exportProducts, fetchAutoPrechecks, moveProducts } from '../api/products'
import type { LibraryProduct } from '../model/contracts'
import type { ProductRow } from '../model/nas-contracts'
import { batchPrecheck, type PrecheckResult } from '../model/precheck'
import ProductPreviewDialog from './ProductPreviewDialog.vue'
import ProductGroupManager from './ProductGroupManager.vue'

const { filters, selected, detailId, list, groups, capabilities, detail, total, refresh, reset } = useProductLibrary()
const message = useMessage()
const keyword = ref(''), capturedFrom = ref<string | null>(null), capturedTo = ref<string | null>(null)
const managerOpen = ref(false), moveOpen = ref(false), moveTarget = ref('ungrouped'), moveIds = ref<string[]>([]), busy = ref(false)
const manualOpen = ref(false), manualSeed = ref('')
const manualProduct = ref<LibraryProduct | null>(null)
const precheckOpen = ref(false), precheckRunning = ref(false)
const precheckIds = ref<string[]>([]), precheckResults = ref<Record<string, PrecheckResult>>({})
const rows = computed(() => list.data.value?.items ?? [])
const autoIds = computed(() => [...new Set([...rows.value.map((row) => row.product_id), ...(detailId.value ? [detailId.value] : [])])])
const autoChecks = useQuery({
  queryKey: computed(() => ['auto-prechecks', autoIds.value] as const),
  enabled: computed(() => capabilities.data.value?.autoPrecheck === true && autoIds.value.length > 0),
  queryFn: ({ signal, queryKey }) => fetchAutoPrechecks([...queryKey[1]], signal),
  refetchInterval: 5_000, retry: false,
})
const autoResults = computed(() => Object.fromEntries((autoChecks.data.value ?? []).map((item) => [item.productId, item])))
const groupItems = computed(() => groups.data.value ?? [])
const canWriteGroups = computed(() => capabilities.data.value?.groupWrites === true)
const preview = computed(() => detailId.value ? detail.data.value ?? null : null)
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
  await refresh()
  detailId.value = id
}

async function startPrecheck() {
  if (!selected.value.length || precheckRunning.value || !capabilities.data.value?.categoryLookup) return
  precheckIds.value = [...selected.value]
  precheckResults.value = {}
  precheckOpen.value = true
  precheckRunning.value = true
  try {
    await batchPrecheck(precheckIds.value, (result) => { precheckResults.value[result.productId] = result })
  } finally { precheckRunning.value = false }
}

function precheckLabel(result: PrecheckResult | undefined) {
  if (!result) return '等待预检'
  return { ready: '已检查', needs_completion: '待完善', needs_category: '待选择类目', failed: '预检失败' }[result.status]
}

function autoPrecheckLabel(id: string) {
  const record = autoResults.value[id]
  if (autoChecks.isError.value) return '暂不可用'
  if (!record) return '—'
  if (record.error) return '等待重试'
  if (record.state === 'pending') return '等待预检'
  if (record.state === 'running') return '预检中'
  return precheckLabel(record.result ?? undefined)
}

function openPrechecked(id: string) {
  precheckOpen.value = false
  detailId.value = id
}

const columns = computed<DataTableColumns<ProductRow>>(() => [
  { type: 'selection', width: 44, fixed: 'left' },
  { title: '商品信息', key: 'title', width: 360, fixed: 'left', render: (row) => h(ProductInfoCell, {
    title: row.title, productId: row.source_product_id || row.product_id, imageUrl: row.main_image_url, density: 'compact',
  }) },
  { title: '来源平台', key: 'source_platform', width: 110, align: 'center', render: (row) => {
    const code = platformCode(row.source_platform)
    return code ? h(PlatformDisplay, { code }) : (row.source_platform || '—')
  } },
  { title: '分组', key: 'group_name', width: 130, align: 'center', render: (row) => row.group_name || '未分组' },
  { title: '店铺', key: 'shop_name', width: 140, align: 'center', ellipsis: { tooltip: true } },
  { title: '类目', key: 'category_path', width: 260, align: 'center', render: (row) => h(NEllipsis, { tooltip: true, lineClamp: 2 }, () => row.category_path || '—') },
  ...(capabilities.data.value?.autoPrecheck ? [{ title: '自动预检', key: 'auto_precheck', width: 120, align: 'center' as const,
    render: (row: ProductRow) => h('span', { title: autoResults.value[row.product_id]?.result?.issues.join('；') || '' }, autoPrecheckLabel(row.product_id)) }] : []),
  { title: '当前价格', key: 'price', width: 120, align: 'center', render: (row) => priceRange(row) },
  { title: 'SKU', key: 'sku_count', width: 80, align: 'center' },
  { title: '采集时间', key: 'captured_at', width: 176, align: 'center', render: (row) => capturedTime(row.captured_at) },
  { title: '操作', key: 'actions', width: 170, fixed: 'right', align: 'center', render: (row) => h('div', { class: 'product-library-actions' }, [
    h(AppButton, { tone: 'link', size: 'small', onClick: () => { detailId.value = row.product_id } }, () => '查看商品'),
    h(AppButton, { size: 'small', disabled: busy.value, onClick: () => download([row.product_id]) }, () => '导出商品数据包'),
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
          <AppButton size="small" :disabled="!selected.length || busy" @click="download(selected)">批量导出商品数据包</AppButton>
          <AppButton size="small" :disabled="!selected.length || precheckRunning || !capabilities.data.value?.categoryLookup" @click="startPrecheck">批量预检</AppButton>
          <AppButton v-if="precheckIds.length" size="small" @click="precheckOpen = true">预检结果 {{ Object.keys(precheckResults).length }}/{{ precheckIds.length }}</AppButton>
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
      :editable="capabilities.data.value?.productEdit === true" @saved="refresh"
      :category-lookup-enabled="capabilities.data.value?.categoryLookup === true"
      :auto-result="detailId && preview?.id === detailId ? autoResults[detailId] : undefined"
      :batch-prediction="detailId && preview?.id === detailId ? (precheckResults[detailId]?.prediction || autoResults[detailId]?.result?.prediction) : undefined"
      :loading="detail.isFetching.value" :error="detail.error.value ? errorText(detail.error.value) : null"
      :can-previous="previewIndex > 0 && !detail.isFetching.value"
      :can-next="previewIndex >= 0 && previewIndex < rows.length - 1 && !detail.isFetching.value"
      :groupable="canWriteGroups" :navigation-items="rows.map((row) => ({ id: row.product_id, title: row.title,
        subtitle: row.source_product_id || row.product_id, imageUrl: row.main_image_url }))"
      @update:show="!$event && (detailId = null)" @navigate-to="detailId = $event" @navigate="navigatePreview"
      @retry="detail.refetch()"
      @export="download([$event.id])" @group="openMove([$event.id])" />
    <ProductGroupManager v-model:show="managerOpen" :groups="groupItems" :writable="canWriteGroups" @changed="groupsChanged" />
    <ProductPreviewDialog :show="manualOpen" :product="manualProduct" :manual-seed="manualSeed"
      creating :editable="capabilities.data.value?.productEdit === true"
      :category-lookup-enabled="capabilities.data.value?.categoryLookup === true"
      @update:show="manualOpen = $event" @created="manualCreated" />
    <AppDialog v-model:show="precheckOpen" title="批量预检" size="lg" positive-text="关闭" :show-negative="false" @confirm="precheckOpen = false">
      <p>已完成 {{ Object.keys(precheckResults).length }} / {{ precheckIds.length }}</p>
      <p>检查标题、主图、SKU 价格及已选类目的必填属性。</p>
      <div v-for="id in precheckIds" :key="id" class="product-library-precheck-row">
        <div><strong>{{ precheckResults[id]?.title || rows.find((row) => row.product_id === id)?.title || id }}</strong>
          <div>{{ precheckLabel(precheckResults[id]) }}<template v-if="precheckResults[id]?.issues.length">：{{ precheckResults[id].issues.join('；') }}</template></div>
        </div>
        <AppButton size="small" :disabled="!precheckResults[id]" @click="openPrechecked(id)">查看商品</AppButton>
      </div>
    </AppDialog>
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
.product-library-precheck-row { display:flex; justify-content:space-between; align-items:center; gap:var(--space-3); padding:var(--space-2) 0; border-bottom:1px solid var(--border-color); }
</style>
