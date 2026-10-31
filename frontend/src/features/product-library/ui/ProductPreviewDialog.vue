<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NDescriptions, NDescriptionsItem, NFormItem, NImage, NSpin, NTab, NText, NTooltip,
  type DataTableColumns, useMessage,
} from 'naive-ui'
import { PlatformDisplay } from '@/entities/platform'
import { ErrorState, LoadingState } from '@/shared/components'
import { AppButton, AppDialog, AppInput, AppTable, AppTabs } from '@/shared/ui'
import { copyText } from '@/shared/utils/copy-text'
import type { LibraryProduct, ProductSku } from '../model/contracts'
import { previewImageUrl } from '../model/preview-image-url'
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
  navigationItems?: ReadonlyArray<{ id: string; title: string; subtitle: string; imageUrl: string | null }>
}>(), {
  loading: false, error: null, canPrevious: false, canNext: false,
  positionLabel: '', exportable: true, groupable: true, navigationItems: () => [],
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
watch(() => props.product?.id, () => {
  imageRetries.value = {}
  imageFallbacks.value = {}
})
watch(() => props.show, (show) => { if (!show) tab.value = 'base' })

function retryImage(key: string) { imageRetries.value[key] = (imageRetries.value[key] ?? 0) + 1 }
function imageSource(key: string, source: string) { return imageFallbacks.value[key] ? source : previewImageUrl(source) }
function fallbackImage(key: string, source: string) {
  if (!imageFallbacks.value[key] && previewImageUrl(source) !== source) imageFallbacks.value[key] = true
}
async function copy(value: string, label: string) {
  try { await copyText(value); message.success(`${label}已复制`) }
  catch { message.error('复制失败，请重试') }
}

const imageSections = computed(() => {
  const product = props.product
  if (!product) return []
  return [
    { key: 'main', label: '主图', images: (product.previewMainImageUrls ??
      (product.mainImageUrl ? [product.mainImageUrl] : [])).map((src, index) => ({
        src, label: `主图 ${index + 1}`, caption: '', skuKey: undefined,
      })) },
    { key: 'sku', label: 'SKU 图', images: product.skus.map((sku) => ({
      src: sku.imageUrl, label: sku.name, caption: sku.sourceSkuId ?? '', skuKey: sku.draftKey,
    })) },
    { key: 'detail', label: '详情图', images: product.detailImageUrls.map((src, index) => ({
      src, label: `详情图 ${index + 1}`, caption: '', skuKey: undefined,
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
const skuColumns: DataTableColumns<ProductSku> = [
  { title: '规格', key: 'name', minWidth: 240, render: (row) => h('div', { class: 'product-preview__sku' }, [
    h(DeferredPreviewThumbnail, { src: row.imageUrl, title: row.name }),
    h('span', row.name || '—'),
  ]) },
  { title: '价格', key: 'price', width: 120, render: (row) => row.currentPrice === null ? '—' : `¥${row.currentPrice}` },
  { title: '库存', key: 'stock', width: 100, render: (row) => row.stockLabel ?? '—' },
  { title: 'SKU ID', key: 'skuId', minWidth: 160, render: (row) => row.sourceSkuId ?? '—' },
  { title: '商家编码', key: 'merchantCode', width: 140, render: () => '—' },
  { title: 'SKU 状态', key: 'skuStatus', width: 110, render: () => '—' },
]
</script>

<template>
  <AppDialog :show="show" title="商品详情" size="workspace" :content-scrollable="false"
    positive-text="关闭" :show-negative="false"
    @update:show="!$event && emit('update:show', false)" @confirm="emit('update:show', false)">
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
            <AppButton size="small" @click="copy(product.title, '商品标题')">复制标题</AppButton>
            <AppButton size="small" @click="copy(basicText, '基础信息')">复制基础信息</AppButton>
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
            <NFormItem label="商品标题"><AppInput :model-value="product.title" aria-label="商品标题" readonly /></NFormItem>
            <NFormItem label="来源类目"><AppInput :model-value="product.category ?? ''" aria-label="来源类目" readonly /></NFormItem>
            <NDescriptions bordered :column="3" label-placement="left">
              <NDescriptionsItem label="来源店铺">{{ product.shopName || '—' }}</NDescriptionsItem>
              <NDescriptionsItem label="当前价格">{{ product.currentPrice === null ? '—' : `¥${product.currentPrice}` }}</NDescriptionsItem>
              <NDescriptionsItem label="采集时间">{{ product.collectedAt }}</NDescriptionsItem>
              <NDescriptionsItem label="SKU 数量">{{ product.skuCount ?? product.skus.length }}</NDescriptionsItem>
              <NDescriptionsItem label="主图">{{ product.mainImageCount ?? 0 }}</NDescriptionsItem>
              <NDescriptionsItem label="详情图">{{ product.detailImageCount ?? 0 }}</NDescriptionsItem>
            </NDescriptions>
          </section>
          <section v-if="tab === 'images'" class="product-preview__image-workspace">
            <article v-for="section in imageSections" :key="section.key" class="product-preview__image-section">
              <header class="product-preview__image-section-header"><strong>{{ section.label }}</strong><NText depth="3">{{ section.images.length }} 张</NText></header>
              <NText v-if="!section.images.length" depth="3">—</NText>
              <div v-else class="product-preview__image-strip">
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
                  <strong>{{ image.label }}</strong>
                  <NTooltip v-if="image.caption"><template #trigger><NText depth="3" class="product-preview__image-caption">{{ image.caption }}</NText></template>{{ image.caption }}</NTooltip>
                </div>
              </div>
            </article>
          </section>
          <section v-if="tab === 'attributes'" class="product-preview__section">
            <NDescriptions v-if="product.attributes.length" bordered :column="3">
              <NDescriptionsItem v-for="item in product.attributes" :key="item.name" :label="item.name">{{ item.value }}</NDescriptionsItem>
            </NDescriptions>
            <NText v-else depth="3">—</NText>
          </section>
          <section v-if="tab === 'sku'" class="product-preview__section">
            <div class="product-preview__section-heading"><strong>规格与 SKU</strong>
              <div class="product-preview__actions"><AppButton size="small" @click="copy(skuText, 'SKU 信息')">复制 SKU</AppButton>
                <AppButton size="small" @click="copy(allText, '全部商品信息')">复制全部信息</AppButton></div>
            </div>
            <AppTable :columns="skuColumns" :data="product.skus" :row-key="(row) => row.draftKey" :scroll-x="970" bordered />
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
.product-preview__section-heading,.product-preview__image-section-header { display:flex; align-items:center; justify-content:space-between; gap:var(--space-2); }
.product-preview__image-section { display:grid; gap:var(--space-2); min-width:0; padding:var(--space-3); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }
.product-preview__image-strip { display:flex; gap:var(--space-3); overflow-x:auto; padding-bottom:var(--space-2); }
.product-preview__image-card { flex:0 0 152px; min-width:0; padding:var(--space-2); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }
.product-preview__image-card strong,.product-preview__image-caption { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-preview__image-canvas { display:grid; place-items:center; width:128px; height:128px; margin-bottom:var(--space-2); }
.product-preview__image-canvas :deep(img) { width:128px; height:128px; object-fit:contain; }
.product-preview__content :deep(.product-preview__sku) { display:flex; align-items:center; gap:var(--space-3); }
.product-preview__content :deep(.product-preview__sku .deferred-preview-thumbnail) { width:64px; height:64px; flex:0 0 64px; }
@media (max-width:820px) { .product-preview__layout { grid-template-columns:minmax(160px,30%) minmax(0,1fr); } .product-preview__header { flex-wrap:wrap; } }
@media (max-width:560px) { .product-preview__layout { grid-template-columns:minmax(0,1fr); grid-template-rows:180px minmax(0,1fr); } }
</style>
