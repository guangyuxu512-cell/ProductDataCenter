<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { NAlert, NFormItem, NInput, NInputNumber, NSelect, NSpin, NSwitch, NTab, NText, useMessage,
  type DataTableColumns } from 'naive-ui'
import { ProductImage } from '@/entities/product'
import { PlatformDisplay } from '@/entities/platform'
import { ErrorState } from '@/shared/components'
import { AppButton, AppDialog, AppInput, AppTable, AppTabs } from '@/shared/ui'
import { fetchEditor, inspectEditor, saveEditor, uploadProductImage } from '../api/editor'
import { buildSkuGrid, type SkuCombination } from '../model/sku-grid'
import { productTitleLength } from '../model/format'
import type { LibraryProduct } from '../model/contracts'
import type { DraftInspection, EditorDimension, EditorImage, EditorSku, ProductEditorDraft, ProductEditorState } from '../model/editor-contracts'
import ProductRangeNavigator from './ProductRangeNavigator.vue'
import DeferredPreviewThumbnail from './DeferredPreviewThumbnail.vue'

const props = withDefaults(defineProps<{
  show: boolean
  productId: string | null
  product: LibraryProduct | null
  navigationItems: ReadonlyArray<{ id: string; title: string; subtitle: string; imageUrl: string | null }>
  canPrevious?: boolean
  canNext?: boolean
  groupable?: boolean
  assetUploads?: boolean
}>(), { canPrevious: false, canNext: false, groupable: false, assetUploads: false })

const emit = defineEmits<{
  'update:show': [value: boolean]
  navigate: [direction: 'previous' | 'next']
  'navigate-to': [id: string]
  group: [id: string]
  saved: []
}>()

const message = useMessage(), client = useQueryClient()
const tab = ref('base'), state = ref<ProductEditorState | null>(null), draft = ref<ProductEditorDraft | null>(null)
const baseline = ref(''), saving = ref(false), uploading = ref(false), guardOpen = ref(false)
const inspecting = ref(false), inspection = ref<DraftInspection | null>(null)
const pendingAction = ref<(() => void) | null>(null)
const pendingVerb = ref<'切换' | '关闭'>('切换')
const confirmation = ref<{ title: string; content: string; positive: string; action: () => void } | null>(null)
const urlDialog = ref(false), newImageUrl = ref(''), fileInput = ref<HTMLInputElement | null>(null)
type ImageTarget = { kind: 'main' | 'detail' } | { kind: 'spec'; dimensionId: string; valueId: string }
const imageTarget = ref<ImageTarget | null>(null)
const currentProduct = computed(() => props.product?.id === props.productId ? props.product : null)
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败'
const query = useQuery({
  queryKey: computed(() => ['product-editor', props.productId] as const),
  enabled: computed(() => props.show && !!props.productId),
  queryFn: ({ queryKey, signal }) => fetchEditor(queryKey[1]!, signal),
  staleTime: 0,
})
const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== baseline.value)
const busy = computed(() => saving.value || uploading.value || inspecting.value)

function applyState(value: ProductEditorState) {
  state.value = value
  draft.value = clone(value.draft)
  baseline.value = JSON.stringify(draft.value)
}
watch(() => props.productId, () => { state.value = null; draft.value = null; baseline.value = ''; tab.value = 'base'; inspection.value = null }, { flush: 'sync' })
watch(() => query.data.value, (value) => {
  if (!value || value.productId !== props.productId) return
  if (!state.value || (!dirty.value && (state.value.revision !== value.revision ||
      state.value.sourceFingerprint !== value.sourceFingerprint || state.value.sourceChanged !== value.sourceChanged))) applyState(value)
}, { immediate: true })

async function saveCurrent(): Promise<boolean> {
  if (!props.productId || !state.value || !draft.value || busy.value) return false
  if (!draft.value.title.trim() || productTitleLength(draft.value.title) > 60) {
    message.error('请填写商品标题，最多 60 个计数单位')
    tab.value = 'base'
    return false
  }
  saving.value = true
  try {
    const saved = await saveEditor(props.productId, state.value.revision, state.value.sourceFingerprint, clone(draft.value))
    applyState(saved)
    client.setQueryData(['product-editor', saved.productId], saved)
    message.success('编辑草稿已保存')
    emit('saved')
    return true
  } catch (error) { message.error(errorText(error)); return false }
  finally { saving.value = false }
}

async function inspectCurrent() {
  if (!props.productId || !state.value || !draft.value || busy.value) return
  const productId = props.productId, snapshot = JSON.stringify(draft.value)
  const revision = state.value.revision, fingerprint = state.value.sourceFingerprint
  inspecting.value = true
  try {
    const result = await inspectEditor(productId, revision, fingerprint, JSON.parse(snapshot) as ProductEditorDraft)
    if (productId !== props.productId || snapshot !== JSON.stringify(draft.value) ||
        revision !== state.value?.revision || fingerprint !== state.value?.sourceFingerprint) {
      message.warning('商品已变更，请重新检查')
      return
    }
    inspection.value = result
  } catch (error) { message.error(errorText(error)) }
  finally { inspecting.value = false }
}

function requestAction(action: () => void, verb: '切换' | '关闭' = '切换') {
  if (busy.value) return
  if (!dirty.value) { action(); return }
  pendingAction.value = action; pendingVerb.value = verb; guardOpen.value = true
}
function finishPending() {
  const action = pendingAction.value
  pendingAction.value = null; guardOpen.value = false
  action?.()
}
async function saveAndContinue() { if (await saveCurrent()) finishPending() }
function cancelPending() { guardOpen.value = false; pendingAction.value = null }
function askConfirmation(title: string, content: string, positive: string, action: () => void) {
  confirmation.value = { title, content, positive, action }
}
function confirmAction() {
  const action = confirmation.value?.action
  confirmation.value = null
  action?.()
}

const titleLength = computed(() => productTitleLength(draft.value?.title ?? ''))
const grid = computed(() => draft.value ? buildSkuGrid(draft.value) : { combinations: [], unmatched: [], tooMany: false })
const activeImageDimension = computed(() => draft.value?.dimensions.find((item) => item.id === draft.value?.imageDimensionId) ?? null)
const sourceSkuImages = computed(() => {
  const seen = new Set<string>()
  return (draft.value?.skus ?? []).flatMap((sku) => {
    const url = sku.sourceImageUrl?.trim()
    if (!url || seen.has(url)) return []
    seen.add(url)
    return [{ url, label: sku.sourceLabel || sku.sourceSkuId || 'SKU' }]
  })
})
const placeholderStocks = computed(() => (draft.value?.skus ?? []).filter((sku) => sku.sourceStockPlaceholder && sku.stock === null).length)
const unconfirmedStocks = computed(() => (draft.value?.skus ?? []).filter((sku) => sku.sourceStockUnconfirmed && sku.stock === null).length)
const unconfirmedPrices = computed(() => (draft.value?.skus ?? []).filter((sku) => sku.sourcePriceUnconfirmed && sku.price === null).length)
let idSequence = 0
function newId(prefix: string) { return `${prefix}-${Date.now().toString(36)}-${++idSequence}` }

function chooseImageDimension(axis: EditorDimension, enabled: boolean) {
  if (!draft.value) return
  if (!enabled) { draft.value.imageDimensionId = null; return }
  const activate = () => {
    if (!draft.value) return
    draft.value.dimensions = [axis, ...draft.value.dimensions.filter((item) => item.id !== axis.id)]
    draft.value.imageDimensionId = axis.id
  }
  if (draft.value.dimensions[0]?.id === axis.id) { activate(); return }
  askConfirmation('开启后该规格组顺序将置顶', '仅第一组规格支持添加规格图片。确认开启后，当前规格组将置顶展示。', '开启', activate)
}

function moveDimension(index: number, delta: number) {
  if (!draft.value) return
  const next = index + delta
  if (next < 0 || next >= draft.value.dimensions.length) return
  const move = () => {
    if (!draft.value) return
    const list = [...draft.value.dimensions]
    ;[list[index], list[next]] = [list[next], list[index]]
    draft.value.dimensions = list
    if (draft.value.imageDimensionId && list[0]?.id !== draft.value.imageDimensionId) draft.value.imageDimensionId = null
  }
  if (draft.value.imageDimensionId && (index === 0 || next === 0)) {
    askConfirmation('调整后将关闭当前规格图', '图片会保留在原规格中。', '确定', move)
  } else move()
}

function addDimension() {
  if (!draft.value || draft.value.dimensions.length >= 3) return
  draft.value.dimensions.push({ id: newId('dimension'), name: '', values: [] })
}
function removeDimension(axis: EditorDimension) {
  if (!draft.value) return
  const remove = () => {
    if (!draft.value) return
    draft.value.dimensions = draft.value.dimensions.filter((item) => item.id !== axis.id)
    if (draft.value.imageDimensionId === axis.id) draft.value.imageDimensionId = null
  }
  if (draft.value.skus.some((sku) => axis.id in sku.specValueIds)) {
    askConfirmation('删除规格类型？', '关联的 SKU 会保留并等待重新匹配。', '删除', remove)
  } else remove()
}
function addValue(axis: EditorDimension) { axis.values.push({ id: newId('value'), sourceValueId: null, name: '', imageUrl: '' }) }
function removeValue(axis: EditorDimension, valueId: string) {
  const remove = () => { axis.values = axis.values.filter((item) => item.id !== valueId) }
  if (draft.value?.skus.some((sku) => sku.specValueIds[axis.id] === valueId)) {
    askConfirmation('删除规格值？', '关联的 SKU 会保留并等待重新匹配。', '删除', remove)
  } else remove()
}
function addCombination(row: SkuCombination) {
  if (!draft.value || row.sku) return
  draft.value.skus.push({ id: newId('sku'), sourceSkuId: null, sourceLabel: '', specValueIds: { ...row.specValueIds },
    unmappedSpecIds: [], price: null, stock: null, merchantCode: '', state: 'unknown' })
}
function removeSku(sku: EditorSku) {
  askConfirmation('删除 SKU？', '采集的原始数据会保留。', '删除',
    () => { if (draft.value) draft.value.skus = draft.value.skus.filter((item) => item.id !== sku.id) })
}
function confirmMapping(sku: EditorSku) {
  if (!draft.value) return
  const dimensions = draft.value.dimensions
  if (!dimensions.length || dimensions.some((axis) => !axis.values.some((value) => value.id === sku.specValueIds[axis.id]))) {
    message.error('请选择每一组规格值'); return
  }
  const cleaned = Object.fromEntries(dimensions.map((axis) => [axis.id, sku.specValueIds[axis.id]]))
  const duplicate = draft.value.skus.some((item) => item.id !== sku.id && !item.unmappedSpecIds.length &&
    dimensions.every((axis) => item.specValueIds[axis.id] === cleaned[axis.id]))
  if (duplicate) { message.error('该 SKU 组合已存在'); return }
  sku.specValueIds = cleaned; sku.unmappedSpecIds = []
}

function imageList(kind: 'main' | 'detail'): EditorImage[] {
  return kind === 'main' ? draft.value?.mainImages ?? [] : draft.value?.detailImages ?? []
}
function assignImage(target: ImageTarget, url: string) {
  if (!draft.value) return
  if (target.kind === 'spec') {
    const item = draft.value.dimensions.find((axis) => axis.id === target.dimensionId)?.values.find((value) => value.id === target.valueId)
    if (item) item.imageUrl = url
  } else imageList(target.kind).push({ id: newId('image'), url })
}
function openImagePicker(target: ImageTarget) { imageTarget.value = target; newImageUrl.value = ''; urlDialog.value = true }
function chooseSourceImage(url: string) {
  if (imageTarget.value) assignImage(imageTarget.value, url)
  urlDialog.value = false
}
function saveImageUrl() {
  try {
    const parsed = new URL(newImageUrl.value.trim())
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error()
    if (imageTarget.value) assignImage(imageTarget.value, parsed.href)
    urlDialog.value = false
  } catch { message.error('请输入有效的图片链接') }
}
async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0], target = imageTarget.value
  input.value = ''
  if (!file || !target || busy.value) return
  uploading.value = true
  try {
    const result = await uploadProductImage(file)
    assignImage(target, result.url)
    urlDialog.value = false
  } catch (error) { message.error(errorText(error)) }
  finally { uploading.value = false }
}
function moveImage(kind: 'main' | 'detail', index: number, direction: number) {
  const list = imageList(kind), next = index + direction
  if (next < 0 || next >= list.length) return
  ;[list[index], list[next]] = [list[next], list[index]]
}
function removeImage(kind: 'main' | 'detail', id: string) {
  if (!draft.value) return
  if (kind === 'main') draft.value.mainImages = draft.value.mainImages.filter((item) => item.id !== id)
  else draft.value.detailImages = draft.value.detailImages.filter((item) => item.id !== id)
}

const skuColumns = computed<DataTableColumns<SkuCombination>>(() => [
  ...(draft.value?.dimensions ?? []).map((axis) => ({
    title: axis.name || '规格', key: axis.id, width: 140,
    render: (row: SkuCombination) => axis.values.find((value) => value.id === row.specValueIds[axis.id])?.name || '—',
  })),
  { title: '价格', key: 'price', width: 120, render: (row) => row.sku
    ? h(NInput, { value: row.sku.price ?? '', placeholder: '价格', inputProps: { 'aria-label': 'SKU 价格' },
      'onUpdate:value': (value: string) => { if (row.sku) row.sku.price = value || null } }) : '—' },
  { title: '库存', key: 'stock', width: 120, render: (row) => row.sku
    ? h(NInputNumber, { value: row.sku.stock, min: 0, max: 2147483647, precision: 0, showButton: false,
      'aria-label': 'SKU 库存', 'onUpdate:value': (value: number | null) => { if (row.sku) row.sku.stock = value } }) : '—' },
  { title: '商家编码', key: 'code', width: 150, render: (row) => row.sku
    ? h(NInput, { value: row.sku.merchantCode, placeholder: '商家编码', inputProps: { 'aria-label': 'SKU 商家编码' },
      'onUpdate:value': (value: string) => { if (row.sku) row.sku.merchantCode = value } }) : '—' },
  { title: 'SKU 状态', key: 'state', width: 140, render: (row) => {
    if (!row.sku) return '未采集'
    if (row.sku.state === 'unknown') return h(NSelect, { value: 'unknown', 'aria-label': 'SKU 状态', options: [
      { label: '未确认', value: 'unknown' }, { label: '在售', value: 'active' }, { label: '下架', value: 'inactive' },
    ], 'onUpdate:value': (value: EditorSku['state']) => { if (row.sku) row.sku.state = value } })
    return h('span', { class: 'product-editor__status' }, [
      h(NSwitch, { value: row.sku.state === 'active', 'aria-label': 'SKU 在售状态',
        'onUpdate:value': (value: boolean) => { if (row.sku) row.sku.state = value ? 'active' : 'inactive' } }),
      row.sku.state === 'active' ? '在售' : '下架',
    ])
  } },
  { title: '操作', key: 'actions', width: 100, render: (row) => row.sku
    ? h(AppButton, { size: 'small', tone: 'link', onClick: () => removeSku(row.sku!) }, () => '删除')
    : h(AppButton, { size: 'small', onClick: () => addCombination(row) }, () => '新增') },
])
</script>

<template>
  <AppDialog :show="show" title="编辑商品" size="workspace" :content-scrollable="false" positive-text="保存"
    :loading="saving" :positive-disabled="!draft || busy" :show-negative="false"
    @update:show="!$event && requestAction(() => emit('update:show', false), '关闭')" @confirm="saveCurrent">
    <template #footer-start><NText depth="3">待预检 · 数据包待生成</NText></template>
    <div class="product-editor__layout">
      <ProductRangeNavigator :items="navigationItems" :selected-id="productId" :can-previous="canPrevious"
        :can-next="canNext" :disabled="busy" @navigate="requestAction(() => emit('navigate', $event))"
        @navigate-to="requestAction(() => emit('navigate-to', $event))" />
      <section class="product-editor__main">
        <div v-if="query.isPending.value || (query.isFetching.value && !draft)" class="product-editor__loading"><NSpin size="small" /></div>
        <ErrorState v-else-if="query.error.value" :description="errorText(query.error.value)" retryable @retry="query.refetch()" />
        <template v-else-if="draft && state">
          <header class="product-editor__header">
            <div class="product-editor__meta">
              <PlatformDisplay v-if="currentProduct?.platform" :code="currentProduct.platform" />
              <span v-else>手动创建</span>
              <span>商品 ID {{ currentProduct?.productId ?? productId }}</span>
              <span v-if="currentProduct?.shopName">来源店铺 {{ currentProduct.shopName }}</span>
              <span>分组 {{ currentProduct?.groupName ?? '未分组' }}</span>
            </div>
            <div class="product-editor__actions">
              <AppButton size="small" :disabled="busy" @click="inspectCurrent">检查商品</AppButton>
              <AppButton size="small" :disabled="!groupable || busy || !productId" @click="productId && emit('group', productId)">移动分组</AppButton>
              <AppButton size="small" disabled>导出商品数据包</AppButton>
            </div>
          </header>
          <AppTabs v-model="tab" class="product-editor__tabs">
            <NTab name="base">基本信息</NTab><NTab name="images">图文信息</NTab>
            <NTab name="attributes">商品属性</NTab><NTab name="sku">规格与 SKU</NTab>
          </AppTabs>
          <div class="product-editor__body">
            <NAlert v-if="state.sourceChanged" type="warning">采集来源已有更新，当前保留的是已保存的编辑草稿。</NAlert>
            <section v-show="tab === 'base'" class="product-editor__section">
              <NFormItem label="商品标题" required>
                <AppInput v-model="draft.title" aria-label="商品标题" />
                <span class="product-editor__count" :class="{ 'product-editor__count--invalid': titleLength > 60 }">{{ titleLength }}/60</span>
                <AppButton size="small" disabled>AI 优化</AppButton>
              </NFormItem>
              <NFormItem label="抖店类目" required>
                <AppInput :model-value="draft.categoryPath" aria-label="抖店类目" readonly />
                <AppButton size="small" disabled>更换类目</AppButton>
              </NFormItem>
            </section>
            <section v-show="tab === 'images'" class="product-editor__section">
              <article v-for="group in (['main', 'detail'] as const)" :key="group" class="product-editor__image-group">
                <header><strong>{{ group === 'main' ? '主图' : '详情图' }}</strong>
                  <div class="product-editor__actions"><AppButton size="small" disabled>AI 创作</AppButton>
                    <AppButton size="small" @click="openImagePicker({ kind: group })">添加图片</AppButton></div>
                </header>
                <div class="product-editor__images">
                  <div v-for="(image, index) in imageList(group)" :key="image.id" class="product-editor__image">
                    <ProductImage :src="image.url || null" :title="group === 'main' ? '主图' : '详情图'" size="thumbnail" />
                    <div class="product-editor__image-actions">
                      <AppButton tone="link" size="small" :disabled="index === 0" @click="moveImage(group, index, -1)">上移</AppButton>
                      <AppButton tone="link" size="small" :disabled="index === imageList(group).length - 1" @click="moveImage(group, index, 1)">下移</AppButton>
                      <AppButton tone="link" size="small" @click="removeImage(group, image.id)">删除</AppButton>
                    </div>
                  </div>
                </div>
              </article>
              <article class="product-editor__image-group">
                <header><strong>规格图</strong><AppButton tone="link" size="small" @click="tab = 'sku'">在规格与 SKU 中设置</AppButton></header>
                <div class="product-editor__images">
                  <div v-for="value in activeImageDimension?.values ?? []" :key="value.id" class="product-editor__image">
                    <ProductImage :src="value.imageUrl || null" :title="value.name" size="thumbnail" /><NText>{{ value.name }}</NText>
                  </div>
                </div>
              </article>
              <article v-if="tab === 'images' && sourceSkuImages.length" class="product-editor__image-group">
                <header><strong>采集 SKU 图</strong></header>
                <div class="product-editor__images">
                  <div v-for="image in sourceSkuImages" :key="image.url" class="product-editor__image">
                    <DeferredPreviewThumbnail :src="image.url" :title="image.label" />
                    <NText class="product-editor__image-label">{{ image.label }}</NText>
                  </div>
                </div>
              </article>
            </section>
            <section v-show="tab === 'attributes'" class="product-editor__section">
              <NAlert type="warning">类目属性规则待接入；来源属性仅供核对。</NAlert>
              <div class="product-editor__attributes">
                <NFormItem v-for="attribute in draft.attributes" :key="attribute.id" :label="attribute.name || attribute.id">
                  <AppInput :model-value="attribute.values.map((value) => value.name).join('、')" readonly />
                </NFormItem>
              </div>
              <template v-if="draft.sourceAttributes?.length">
                <strong>来源属性</strong>
                <div class="product-editor__attributes">
                  <NFormItem v-for="attribute in draft.sourceAttributes" :key="attribute.id" :label="attribute.name || attribute.id">
                    <AppInput :model-value="attribute.values.map((value) => value.name).join('、')" readonly />
                  </NFormItem>
                </div>
              </template>
            </section>
            <section v-show="tab === 'sku'" class="product-editor__section">
              <div class="product-editor__section-heading"><strong>销售规格</strong><AppButton size="small" :disabled="draft.dimensions.length >= 3" @click="addDimension">添加规格类型</AppButton></div>
              <div v-for="(axis, axisIndex) in draft.dimensions" :key="axis.id" class="product-editor__axis">
                <div class="product-editor__axis-heading">
                  <AppInput v-model="axis.name" aria-label="规格类型" />
                  <span class="product-editor__status"><NSwitch :value="draft.imageDimensionId === axis.id" :aria-label="`${axis.name}添加规格图`"
                    @update:value="chooseImageDimension(axis, $event)" />添加规格图</span>
                  <div class="product-editor__actions"><AppButton tone="link" size="small" :disabled="axisIndex === 0" @click="moveDimension(axisIndex, -1)">上移</AppButton>
                    <AppButton tone="link" size="small" :disabled="axisIndex === draft.dimensions.length - 1" @click="moveDimension(axisIndex, 1)">下移</AppButton>
                    <AppButton tone="link" size="small" @click="removeDimension(axis)">删除</AppButton></div>
                </div>
                <div class="product-editor__values">
                  <div v-for="value in axis.values" :key="value.id" class="product-editor__value">
                    <AppButton v-if="draft.imageDimensionId === axis.id" size="small" @click="openImagePicker({ kind: 'spec', dimensionId: axis.id, valueId: value.id })">{{ value.imageUrl ? '换图' : '加图' }}</AppButton>
                    <AppInput v-model="value.name" aria-label="规格值" />
                    <AppButton v-if="draft.imageDimensionId === axis.id && value.imageUrl" tone="link" size="small" @click="value.imageUrl = ''">删除图片</AppButton>
                    <AppButton tone="link" size="small" @click="removeValue(axis, value.id)">删除</AppButton>
                  </div>
                  <AppButton size="small" @click="addValue(axis)">添加规格值</AppButton>
                </div>
              </div>
              <div class="product-editor__section-heading"><strong>价格与库存</strong></div>
              <NAlert v-if="placeholderStocks" type="warning">{{ placeholderStocks }} 个 SKU 的采集库存为占位值，请填写库存。</NAlert>
              <NAlert v-if="unconfirmedStocks" type="warning">{{ unconfirmedStocks }} 个 SKU 的采集库存需确认，请填写库存。</NAlert>
              <NAlert v-if="unconfirmedPrices" type="warning">{{ unconfirmedPrices }} 个 SKU 的采集价格需确认，请填写价格。</NAlert>
              <NAlert v-if="grid.tooMany" type="warning">规格组合超过 1000 项，请减少规格值后编辑。</NAlert>
              <AppTable :columns="skuColumns" :data="grid.combinations" :row-key="(row) => (row as SkuCombination).key"
                :scroll-x="Math.max(700, draft.dimensions.length * 140 + 630)" bordered />
              <div v-if="grid.unmatched.length" class="product-editor__unmatched">
                <strong>待匹配的 SKU</strong>
                <div v-for="sku in grid.unmatched" :key="sku.id" class="product-editor__unmatched-row">
                  <NText>{{ sku.sourceLabel || sku.sourceSkuId || 'SKU' }}</NText>
                  <NSelect v-for="axis in draft.dimensions" :key="axis.id" :value="sku.specValueIds[axis.id] || null"
                    :placeholder="axis.name || '规格'" :options="axis.values.map((value) => ({ label: value.name, value: value.id }))"
                    @update:value="sku.specValueIds[axis.id] = String($event)" />
                  <AppButton size="small" @click="confirmMapping(sku)">确认规格</AppButton><AppButton tone="link" size="small" @click="removeSku(sku)">删除</AppButton>
                </div>
              </div>
            </section>
          </div>
        </template>
      </section>
    </div>
  </AppDialog>
  <AppDialog :show="guardOpen" title="当前商品有未保存的修改" :positive-text="`保存并${pendingVerb}`" negative-text="取消"
    :loading="saving" @confirm="saveAndContinue" @cancel="cancelPending" @update:show="!$event && cancelPending()">
    <template #footer-start><AppButton :disabled="saving" @click="finishPending">放弃修改</AppButton></template>
  </AppDialog>
  <AppDialog :show="!!confirmation" :title="confirmation?.title ?? ''" :positive-text="confirmation?.positive ?? '确定'"
    negative-text="取消" @confirm="confirmAction" @cancel="confirmation = null" @update:show="!$event && (confirmation = null)">
    {{ confirmation?.content }}
  </AppDialog>
  <AppDialog :show="!!inspection" title="商品检查" positive-text="关闭" :show-negative="false"
    @confirm="inspection = null" @update:show="!$event && (inspection = null)">
    <NAlert type="warning">平台类目与属性预检尚未接入，商品数据包暂不能发布。</NAlert>
    <div v-if="inspection?.issues.length" class="product-editor__issues">
      <AppButton v-for="(issue, index) in inspection.issues" :key="`${issue.code}-${index}`" tone="link"
        @click="tab = issue.tab; inspection = null">{{ issue.message }}</AppButton>
    </div>
    <NText v-else>本地检查通过。</NText>
  </AppDialog>
  <AppDialog :show="urlDialog" title="添加图片" positive-text="添加链接" negative-text="取消" :loading="uploading"
    @confirm="saveImageUrl" @cancel="urlDialog = false" @update:show="!$event && (urlDialog = false)">
    <NFormItem label="图片链接"><AppInput v-model="newImageUrl" aria-label="图片链接" /></NFormItem>
    <div v-if="imageTarget?.kind === 'spec' && sourceSkuImages.length" class="product-editor__source-picker">
      <strong>采集 SKU 图</strong>
      <div class="product-editor__images">
        <AppButton v-for="image in sourceSkuImages" :key="image.url" class="product-editor__source-choice"
          tone="text" @click="chooseSourceImage(image.url)">
          <span class="product-editor__source-thumb"><DeferredPreviewThumbnail :src="image.url" :title="image.label" /></span>
          <span class="product-editor__image-label">{{ image.label }}</span>
        </AppButton>
      </div>
    </div>
    <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden @change="selectFile" />
    <AppButton :disabled="!assetUploads || uploading" @click="fileInput?.click()">上传本地图片</AppButton>
  </AppDialog>
</template>

<style scoped>
.product-editor__layout { display:grid; grid-template-columns:clamp(260px,20vw,320px) minmax(0,1fr); gap:var(--space-4); height:100%; min-height:0; overflow:hidden; }
.product-editor__main { display:flex; flex-direction:column; min-width:0; min-height:0; overflow:hidden; }
.product-editor__header { display:flex; justify-content:space-between; gap:var(--space-3); align-items:flex-start; padding-bottom:var(--space-3); }
.product-editor__meta,.product-editor__actions,.product-editor__status { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.product-editor__meta { color:var(--text-secondary); font-size:var(--font-size-secondary); }
.product-editor__body { min-height:0; overflow:auto; padding:var(--space-3) var(--space-1) var(--space-3) 0; scrollbar-gutter:stable; }
.product-editor__section { display:grid; gap:var(--space-4); }
.product-editor__section :deep(.n-form-item-feedback-wrapper) { min-height:0; }
.product-editor__section :deep(.n-form-item-blank) { gap:var(--space-2); }
.product-editor__count { white-space:nowrap; color:var(--text-secondary); }
.product-editor__count--invalid { color:var(--color-error); }
.product-editor__image-group { display:grid; gap:var(--space-2); }
.product-editor__image-group > header,.product-editor__section-heading { display:flex; align-items:center; justify-content:space-between; gap:var(--space-2); }
.product-editor__images { display:flex; gap:var(--space-3); overflow-x:auto; padding-bottom:var(--space-2); }
.product-editor__image { flex:0 0 128px; min-width:0; padding:var(--space-2); border:1px solid var(--border-subtle); border-radius:var(--radius-card); text-align:center; }
.product-editor__image :deep(.product-image) { --product-image-size:112px; }
.product-editor__image :deep(.deferred-preview-thumbnail) { display:block; height:112px; }
.product-editor__image-label { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-editor__source-picker { display:grid; gap:var(--space-2); margin-bottom:var(--space-3); }
.product-editor__issues { display:grid; justify-items:start; gap:var(--space-1); margin-top:var(--space-3); }
.product-editor__source-choice { flex:0 0 104px; min-width:0; height:auto; padding:var(--space-2); display:grid; justify-items:center; }
.product-editor__source-thumb { display:block; width:80px; height:80px; pointer-events:none; }
.product-editor__source-thumb :deep(.product-image) { --product-image-size:80px; }
.product-editor__image-actions { display:flex; justify-content:center; gap:var(--space-1); }
.product-editor__attributes { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-3); }
.product-editor__axis { display:grid; gap:var(--space-3); padding:var(--space-3); background:var(--bg-surface-raised); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }
.product-editor__axis-heading,.product-editor__values,.product-editor__value,.product-editor__unmatched-row { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.product-editor__axis-heading > :first-child { width:150px; }
.product-editor__axis-heading > .product-editor__actions { margin-left:auto; }
.product-editor__value > :deep(.n-input) { width:140px; }
.product-editor__unmatched { display:grid; gap:var(--space-2); }
.product-editor__unmatched-row :deep(.n-select) { width:150px; }
.product-editor__loading { display:grid; place-items:center; flex:1; }
@media (max-width:820px) { .product-editor__layout { grid-template-columns:minmax(160px,30%) minmax(0,1fr); } .product-editor__header { flex-wrap:wrap; } .product-editor__attributes { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:560px) { .product-editor__layout { grid-template-columns:minmax(0,1fr); grid-template-rows:180px minmax(0,1fr); } }
</style>
