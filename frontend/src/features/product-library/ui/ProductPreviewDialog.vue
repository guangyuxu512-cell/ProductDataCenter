<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NDropdown, NFormItem, NImage, NSelect, NSpin, NSwitch, NTab, NText,
  type DataTableColumns, useMessage,
} from 'naive-ui'
import { PlatformDisplay } from '@/entities/platform'
import { ErrorState, LoadingState } from '@/shared/components'
import { AppButton, AppDialog, AppInput, AppTable, AppTabs } from '@/shared/ui'
import { copyText } from '@/shared/utils/copy-text'
import { fetchCategoryAttributes, fetchOriginalCategoryAttributes, searchCategoryCandidates,
  type CategoryAttribute, type CategoryCandidate } from '../api/category-lookup'
import type { LibraryProduct, ProductSku } from '../model/contracts'
import { previewImageUrl } from '../model/preview-image-url'
import { sourceSpecLayout } from '../model/source-spec-layout'
import DeferredPreviewThumbnail from './DeferredPreviewThumbnail.vue'
import ProductRangeNavigator from './ProductRangeNavigator.vue'

const props = withDefaults(defineProps<{
  show: boolean
  product: LibraryProduct | null
  loading?: boolean
  error?: string | null
  canPrevious?: boolean
  canNext?: boolean
  positionLabel?: string
  exportable?: boolean
  groupable?: boolean
  categoryLookupEnabled?: boolean
  navigationItems?: ReadonlyArray<{ id: string; title: string; subtitle: string; imageUrl: string | null }>
}>(), {
  loading: false, error: null, canPrevious: false, canNext: false,
  positionLabel: '', exportable: true, groupable: true, categoryLookupEnabled: false, navigationItems: () => [],
})
const emit = defineEmits<{
  'update:show': [value: boolean]
  export: [product: LibraryProduct]
  group: [product: LibraryProduct]
  retry: []
  navigate: [direction: 'previous' | 'next']
  'navigate-to': [id: string]
}>()

const message = useMessage()
const tab = ref('base')
const imageRetries = ref<Record<string, number>>({})
const imageFallbacks = ref<Record<string, boolean>>({})
const categoryBusy = ref(false)
const categoryCandidates = ref<CategoryCandidate[]>([])
const selectedCategory = ref<string | null>(null)
const categoryShop = ref<string | null>(null)
const categoryAttributes = ref<CategoryAttribute[]>([])
const categorySchemaLoaded = ref(false)
const categoryError = ref(false)
let categoryRequest = 0
watch(() => [props.show, props.loading, props.categoryLookupEnabled, props.product?.id,
  props.product?.sourceCategoryId] as const, () => {
  imageRetries.value = {}
  imageFallbacks.value = {}
  categoryRequest += 1
  categoryCandidates.value = []; selectedCategory.value = null; categoryShop.value = null
  categoryAttributes.value = []; categorySchemaLoaded.value = false; categoryBusy.value = false; categoryError.value = false
  const product = props.product
  if (!props.show || props.loading || !props.categoryLookupEnabled || !product ||
      product.platform !== 'douyin' || !product.sourceCategoryId) return
  const label = product.category || `原类目 ${product.sourceCategoryId}`
  selectedCategory.value = product.sourceCategoryId
  categoryCandidates.value = [{ id: product.sourceCategoryId, name: label, path: label }]
  if (tab.value === 'attributes') void loadOriginalAttributes()
}, { immediate: true })
watch(() => props.show, (show) => { if (!show) tab.value = 'base' })
watch(tab, (value) => { if (value === 'attributes') void loadOriginalAttributes() })

function retryImage(key: string) { imageRetries.value[key] = (imageRetries.value[key] ?? 0) + 1 }
function imageSource(key: string, source: string) { return imageFallbacks.value[key] ? source : previewImageUrl(source) }
function fallbackImage(key: string, source: string) {
  if (!imageFallbacks.value[key] && previewImageUrl(source) !== source) imageFallbacks.value[key] = true
}
async function copy(value: string, label: string) {
  try { await copyText(value); message.success(`${label}已复制`) }
  catch { message.error('复制失败，请重试') }
}
function copyFromMenu(key: string) {
  if (key === 'title' && props.product) void copy(props.product.title, '商品标题')
  if (key === 'basic') void copy(basicText.value, '基础信息')
}

async function findCategories() {
  const product = props.product
  if (!product || categoryBusy.value || !props.categoryLookupEnabled) return
  const request = ++categoryRequest
  const keyword = (product.category?.split(/\s*(?:→|>|》|\/|\|)\s*/).filter(Boolean).at(-1) || product.title).slice(0, 120)
  categoryBusy.value = true; selectedCategory.value = null; categoryShop.value = null
  categoryCandidates.value = []; categoryAttributes.value = []; categorySchemaLoaded.value = false; categoryError.value = false
  try {
    const result = await searchCategoryCandidates(keyword)
    if (request !== categoryRequest) return
    categoryCandidates.value = result.candidates; categoryShop.value = result.shopId
    if (!result.candidates.length) message.warning('没有找到类目候选')
  } catch { if (request === categoryRequest) message.error('类目查询失败，请稍后重试') }
  finally { if (request === categoryRequest) categoryBusy.value = false }
}

async function loadOriginalAttributes() {
  const product = props.product
  const categoryId = product?.sourceCategoryId
  if (!props.show || props.loading || !props.categoryLookupEnabled || product?.platform !== 'douyin' ||
      !categoryId || selectedCategory.value !== categoryId || categoryShop.value ||
      categoryBusy.value || categorySchemaLoaded.value) return
  const request = ++categoryRequest
  categoryBusy.value = true; categoryError.value = false
  try {
    const result = await fetchOriginalCategoryAttributes(categoryId, product.title)
    if (request !== categoryRequest) return
    categoryShop.value = result.shopId; categoryAttributes.value = result.attributes; categorySchemaLoaded.value = true
  } catch { if (request === categoryRequest) categoryError.value = true }
  finally { if (request === categoryRequest) categoryBusy.value = false }
}

async function selectCategory(value: string | null) {
  const request = ++categoryRequest
  selectedCategory.value = value; categoryAttributes.value = []; categorySchemaLoaded.value = false; categoryError.value = false
  const product = props.product, shop = categoryShop.value
  if (!value || !product || !shop) { categoryBusy.value = false; return }
  categoryBusy.value = true
  try {
    const result = await fetchCategoryAttributes(shop, value, product.title)
    if (request === categoryRequest) { categoryAttributes.value = result.attributes; categorySchemaLoaded.value = true }
  } catch { if (request === categoryRequest) message.error('属性读取失败，请重新选择类目') }
  finally { if (request === categoryRequest) categoryBusy.value = false }
}

const imageSections = computed(() => {
  const product = props.product
  if (!product) return []
  return [
    { key: 'main', label: '主图', images: (product.previewMainImageUrls ??
      (product.mainImageUrl ? [product.mainImageUrl] : [])).map((src, index) => ({
        src, label: `主图 ${index + 1}`, caption: '', skuKey: undefined,
      })) },
    { key: 'detail', label: '详情图', images: product.detailImageUrls.map((src, index) => ({
      src, label: `详情图 ${index + 1}`, caption: '', skuKey: undefined,
    })) },
    { key: 'sku', label: '规格图', images: (product.previewSkuImageUrls ??
      product.skus.flatMap((sku) => sku.imageUrl ? [sku.imageUrl] : [])).map((src, index) => ({
      src, label: `规格图 ${index + 1}`, caption: '', skuKey: undefined,
    })) },
  ]
})
const basicText = computed(() => {
  const item = props.product
  if (!item) return ''
  return [
    `商品标题：${item.title}`, `商品 ID：${item.productId}`, `来源平台：${item.platform}`,
    `来源店铺：${item.shopName || '—'}`, `来源类目：${item.category ?? '—'}`,
    `当前价格：${item.currentPrice === null ? '—' : `¥${item.currentPrice}`}`,
    `商品分组：${item.groupName ?? '未分组'}`, `采集时间：${item.collectedAt}`,
  ].join('\n')
})
const skuText = computed(() => (props.product?.skus ?? []).map((sku) =>
  `${sku.name}\t${sku.sourceSkuId ?? '—'}\t${sku.currentPrice === null ? '—' : `¥${sku.currentPrice}`}\t${sku.stockLabel ?? '—'}`,
).join('\n'))
const allText = computed(() => {
  const item = props.product
  return item ? [basicText.value, '', 'SKU：', skuText.value, '', '属性：',
    ...item.attributes.map((attribute) => `${attribute.name}：${attribute.value}`)].join('\n') : ''
})
const titleLength = computed(() => Array.from(props.product?.title ?? '')
  .reduce((sum, character) => sum + ((character.codePointAt(0) ?? 0) > 127 ? 2 : 1), 0))
const specLayout = computed(() => sourceSpecLayout(props.product?.skus ?? []))
const skuColumns = computed<DataTableColumns<ProductSku>>(() => {
  const layout = specLayout.value
  const specColumns: DataTableColumns<ProductSku> = layout
    ? layout.axes.map((axis, index) => ({ title: axis.name, key: `spec-${index}`, minWidth: 140,
      render: (row: ProductSku) => layout.rows[row.draftKey]?.[index] ?? '—' }))
    : [{ title: '规格', key: 'name', minWidth: 240, render: (row: ProductSku) =>
      h('div', { class: 'product-preview__sku' }, [
        h(DeferredPreviewThumbnail, { src: row.imageUrl, title: row.name }), h('span', row.name || '—'),
      ]) }]
  return [
    ...specColumns,
    { title: '价格', key: 'price', width: 130, render: (row) => h(AppInput, {
      modelValue: row.currentPrice === null ? '' : `¥${row.currentPrice}`, disabled: true, ariaLabel: 'SKU 价格',
    }) },
    { title: '库存', key: 'stock', width: 120, render: (row) => h(AppInput, {
      modelValue: row.stockLabel ?? '', disabled: true, ariaLabel: 'SKU 库存',
    }) },
    { title: 'SKU ID', key: 'skuId', minWidth: 170, render: (row) => row.sourceSkuId ?? '—' },
    { title: '商家编码', key: 'merchantCode', width: 150, render: () => h(AppInput, {
      modelValue: '', disabled: true, ariaLabel: 'SKU 商家编码',
    }) },
    { title: 'SKU 状态', key: 'skuStatus', width: 110, render: () => '—' },
    { title: '操作', key: 'actions', width: 80, render: () => h(AppButton, {
      tone: 'link', size: 'small', disabled: true,
    }, () => '删除') },
  ]
})
</script>

<template>
  <AppDialog :show="show" title="编辑商品" size="workspace" :content-scrollable="false"
    positive-text="保存" negative-text="关闭" :positive-disabled="true" positive-disabled-reason="商品编辑尚未接入"
    @update:show="!$event && emit('update:show', false)">
    <ErrorState v-if="error" :description="error" retryable @retry="emit('retry')" />
    <LoadingState v-else-if="!product" />
    <div v-else class="product-preview__layout" :aria-busy="loading">
      <div v-if="loading" class="product-preview__loading-mask" role="status" aria-label="加载中"><NSpin size="small" /></div>
      <ProductRangeNavigator :items="navigationItems" :selected-id="product.id" :position-label="positionLabel"
        :can-previous="canPrevious" :can-next="canNext" :disabled="loading"
        @navigate="emit('navigate', $event)" @navigate-to="emit('navigate-to', $event)" />
      <section class="product-preview__main" :inert="loading || undefined">
        <header class="product-preview__header">
          <div class="product-preview__meta">
            <PlatformDisplay :code="product.platform" />
            <span>商品 ID {{ product.productId }}</span>
            <span v-if="product.shopName">来源店铺 {{ product.shopName }}</span>
            <span>分组 {{ product.groupName ?? '未分组' }}</span>
          </div>
          <div class="product-preview__actions">
            <NDropdown trigger="click" :options="[{ label: '复制标题', key: 'title' }, { label: '复制基础信息', key: 'basic' }]" @select="copyFromMenu">
              <AppButton size="small">更多</AppButton>
            </NDropdown>
            <AppButton size="small" :disabled="!groupable" @click="emit('group', product)">移动分组</AppButton>
            <AppButton tone="primary" size="small" :disabled="!exportable" @click="emit('export', product)">导出商品数据包</AppButton>
          </div>
        </header>
        <AppTabs v-model="tab" class="product-preview__tabs">
          <NTab name="base" role="tab" :aria-selected="tab === 'base'">基本信息</NTab>
          <NTab name="images" role="tab" :aria-selected="tab === 'images'">图文信息</NTab>
          <NTab name="attributes" role="tab" :aria-selected="tab === 'attributes'">商品属性</NTab>
          <NTab name="sku" role="tab" :aria-selected="tab === 'sku'">规格与 SKU</NTab>
        </AppTabs>
        <div class="product-preview__content" :inert="loading || undefined">
          <section v-if="tab === 'base'" class="product-preview__section">
            <NFormItem label="商品标题" required>
              <AppInput :model-value="product.title" aria-label="商品标题" readonly />
              <span class="product-preview__count">{{ titleLength }}/60</span>
              <AppButton size="small" disabled>AI 优化</AppButton>
            </NFormItem>
            <NFormItem label="抖店类目" required>
              <template v-if="categoryLookupEnabled">
                <NSelect :value="selectedCategory" aria-label="抖店类目" filterable clearable
                  :disabled="categoryBusy || !categoryCandidates.length"
                  :options="categoryCandidates.map((item) => ({ label: item.path || item.name, value: item.id }))"
                  @update:value="selectCategory" />
                <AppButton size="small" :loading="categoryBusy" @click="findCategories">查找类目</AppButton>
              </template>
              <template v-else>
                <AppInput model-value="" aria-label="抖店类目" disabled />
                <AppButton size="small" disabled>更换类目</AppButton>
              </template>
            </NFormItem>
            <NText v-if="selectedCategory" depth="3">当前类目和属性仅供查看，尚未保存</NText>
            <NText v-if="product.category" depth="3">来源类目：{{ product.category }}</NText>
            <NText v-if="categoryLookupEnabled && product.platform !== 'douyin'" depth="3">平台推荐类目尚未接通，可手动查找类目</NText>
          </section>
          <section v-if="tab === 'images'" class="product-preview__image-workspace">
            <article v-for="section in imageSections" :key="section.key" class="product-preview__image-section">
              <header class="product-preview__image-section-header">
                <strong>{{ section.label }}</strong>
                <div v-if="section.key !== 'sku'" class="product-preview__actions">
                  <AppButton size="small" disabled>AI 创作</AppButton><AppButton size="small" disabled>添加图片</AppButton>
                </div>
                <AppButton v-else tone="link" size="small" @click="tab = 'sku'">在规格与 SKU 中设置</AppButton>
              </header>
              <div class="product-preview__image-strip">
                <div v-for="(image, index) in section.images" :key="image.skuKey ?? `${section.key}:${image.src}:${index}`" class="product-preview__image-card">
                  <div class="product-preview__image-canvas">
                    <NImage v-if="image.src" :key="imageRetries[`${section.key}:${index}`] ?? 0"
                      :src="imageSource(`${section.key}:${index}`, image.src)" :preview-src="image.src"
                      :alt="`${product.title} ${image.label}`" lazy object-fit="contain"
                      :img-props="{ referrerpolicy: 'no-referrer' }"
                      @error="fallbackImage(`${section.key}:${index}`, image.src)">
                      <template #error><AppButton size="small" @click.stop="retryImage(`${section.key}:${index}`)">重试</AppButton></template>
                    </NImage>
                    <NText v-else depth="3">—</NText>
                  </div>
                  <div v-if="section.key !== 'sku'" class="product-preview__image-actions">
                    <AppButton tone="link" size="small" disabled>上移</AppButton>
                    <AppButton tone="link" size="small" disabled>下移</AppButton>
                    <AppButton tone="link" size="small" disabled>删除</AppButton>
                  </div>
                  <NText v-else class="product-preview__image-caption">{{ image.label }}</NText>
                </div>
              </div>
            </article>
          </section>
          <section v-if="tab === 'attributes'" class="product-preview__section">
            <NText v-if="categoryLookupEnabled && product.platform === 'douyin' && !product.sourceCategoryId && !selectedCategory" depth="3">原数据包缺少抖店类目 ID，请手动查找并选择类目</NText>
            <NText v-else-if="categoryLookupEnabled && !selectedCategory" depth="3">请先查找并选择抖店类目</NText>
            <NText v-else-if="categoryBusy" depth="3">正在读取类目属性…</NText>
            <div v-else-if="categoryError"><NText depth="3">原类目属性读取失败</NText><AppButton size="small" @click="loadOriginalAttributes">重试</AppButton></div>
            <NText v-else-if="categorySchemaLoaded && !categoryAttributes.length" depth="3">当前类目没有可显示的属性</NText>
            <NText v-else-if="categorySchemaLoaded" depth="3">同名属性显示来源值，尚未校验或保存</NText>
            <div class="product-preview__attributes">
              <NFormItem v-for="item in categoryAttributes" :key="item.id" :label="item.label" :required="item.required">
                <AppInput :model-value="product.attributes.find((source) => source.name === item.label)?.value ?? ''" readonly />
              </NFormItem>
              <NFormItem v-for="item in categorySchemaLoaded ? [] : product.attributes" :key="item.name" :label="item.name">
                <AppInput :model-value="item.value" readonly />
              </NFormItem>
            </div>
          </section>
          <section v-if="tab === 'sku'" class="product-preview__section">
            <div class="product-preview__section-heading"><strong>销售规格</strong>
              <AppButton size="small" disabled>添加规格类型</AppButton>
            </div>
            <div v-for="axis in specLayout?.axes ?? []" :key="axis.name" class="product-preview__axis">
              <div class="product-preview__axis-heading">
                <AppInput :model-value="axis.name" aria-label="规格类型" readonly />
                <span class="product-preview__status"><NSwitch :value="false" disabled />添加规格图</span>
                <div class="product-preview__actions">
                  <AppButton tone="link" size="small" disabled>上移</AppButton><AppButton tone="link" size="small" disabled>下移</AppButton>
                  <AppButton tone="link" size="small" disabled>删除</AppButton>
                </div>
              </div>
              <div class="product-preview__values">
                <div v-for="value in axis.values" :key="value" class="product-preview__value">
                  <AppInput :model-value="value" :aria-label="`${axis.name}规格值`" readonly />
                  <AppButton tone="link" size="small" disabled>删除</AppButton>
                </div>
                <AppButton size="small" disabled>添加规格值</AppButton>
              </div>
            </div>
            <div class="product-preview__section-heading"><strong>价格与库存</strong>
              <div class="product-preview__actions"><AppButton size="small" @click="copy(skuText, 'SKU 信息')">复制 SKU</AppButton>
                <AppButton size="small" @click="copy(allText, '全部商品信息')">复制全部信息</AppButton></div>
            </div>
            <AppTable :columns="skuColumns" :data="product.skus" :row-key="(row) => row.draftKey" :scroll-x="1000" bordered />
          </section>
        </div>
      </section>
    </div>
  </AppDialog>
</template>

<style scoped>
.product-preview__layout { position:relative; display:grid; grid-template-columns:clamp(260px,20vw,320px) minmax(0,1fr); gap:var(--space-4); height:100%; min-height:0; overflow:hidden; }
.product-preview__main { display:flex; flex-direction:column; min-width:0; min-height:0; overflow:hidden; }
.product-preview__loading-mask { position:absolute; inset:0; z-index:2; display:grid; place-items:center; background:color-mix(in srgb,var(--bg-surface-solid) 55%,transparent); }
.product-preview__header { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--space-3); padding-bottom:var(--space-3); }
.product-preview__meta,.product-preview__actions { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.product-preview__meta { color:var(--text-secondary); font-size:var(--font-size-secondary); }
.product-preview__tabs { flex:0 0 auto; }
.product-preview__content { min-width:0; min-height:0; flex:1; overflow:auto; padding:var(--space-3) var(--space-1) var(--space-3) 0; scrollbar-gutter:stable; }
.product-preview__section,.product-preview__image-workspace { display:grid; grid-template-columns:minmax(0,1fr); min-width:0; gap:var(--space-4); }
.product-preview__section :deep(.n-form-item-feedback-wrapper) { min-height:0; }
.product-preview__section :deep(.n-form-item-blank) { gap:var(--space-2); }
.product-preview__count { white-space:nowrap; color:var(--text-secondary); }
.product-preview__section-heading,.product-preview__image-section-header { display:flex; align-items:center; justify-content:space-between; gap:var(--space-2); }
.product-preview__image-section { display:grid; gap:var(--space-2); min-width:0; }
.product-preview__image-strip { display:flex; gap:var(--space-3); overflow-x:auto; padding-bottom:var(--space-2); }
.product-preview__image-card { flex:0 0 128px; min-width:0; padding:var(--space-2); border:1px solid var(--border-subtle); border-radius:var(--radius-card); text-align:center; }
.product-preview__image-card strong,.product-preview__image-caption { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-preview__image-canvas { display:grid; place-items:center; width:112px; height:112px; margin-bottom:var(--space-2); }
.product-preview__image-canvas :deep(img) { width:112px; height:112px; object-fit:contain; }
.product-preview__image-actions { display:flex; justify-content:center; gap:var(--space-1); }
.product-preview__attributes { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-3); }
.product-preview__axis { display:grid; gap:var(--space-3); padding:var(--space-3); background:var(--bg-surface-raised); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }
.product-preview__axis-heading,.product-preview__values,.product-preview__value { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.product-preview__axis-heading > :first-child { width:150px; }
.product-preview__axis-heading > .product-preview__actions { margin-left:auto; }
.product-preview__value > :deep(.n-input) { width:140px; }
.product-preview__status { display:flex; align-items:center; gap:var(--space-2); color:var(--text-secondary); }
.product-preview__content :deep(.product-preview__sku) { display:flex; align-items:center; gap:var(--space-3); }
.product-preview__content :deep(.product-preview__sku .deferred-preview-thumbnail) { width:64px; height:64px; flex:0 0 64px; }
@media (max-width:820px) { .product-preview__layout { grid-template-columns:minmax(160px,30%) minmax(0,1fr); } .product-preview__header { flex-wrap:wrap; } .product-preview__attributes { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:560px) { .product-preview__layout { grid-template-columns:minmax(0,1fr); grid-template-rows:180px minmax(0,1fr); } }
</style>
