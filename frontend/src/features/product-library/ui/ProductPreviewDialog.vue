<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NAlert,
  NDescriptions,
  NDescriptionsItem,
  NForm,
  NFormItem,
  NImage,
  NSpin,
  NList,
  NListItem,
  NTabPane,
  NText,
  NTooltip,
  type DataTableColumns,
  useDialog,
  useMessage,
} from 'naive-ui'
import DeferredPreviewThumbnail from './DeferredPreviewThumbnail.vue'
import ProductRangeNavigator from './ProductRangeNavigator.vue'
import { previewImageUrl } from '../model/preview-image-url'
import { PlatformDisplay } from '@/entities/platform'
import { ErrorState, LoadingState, StatusTag } from '@/shared/components'
import { AppButton, AppDialog, AppInput, AppTable, AppTabs } from '@/shared/ui'
import { copyText } from '@/shared/utils/copy-text'
import type {
  LibraryProduct,
  ProductEditDraft,
  ProductEditSku,
  ProductSku,
} from '../model/contracts'

const props = withDefaults(
  defineProps<{
    show: boolean
    product: LibraryProduct | null
    saving?: boolean
    loading?: boolean
    error?: string | null
    canPrevious?: boolean
    canNext?: boolean
    positionLabel?: string
    editable?: boolean
    exportable?: boolean
    groupable?: boolean
    navigationItems?: ReadonlyArray<{
      id: string
      title: string
      subtitle: string
      imageUrl: string | null
    }>
  }>(),
  {
    saving: false,
    loading: false,
    error: null,
    canPrevious: false,
    canNext: false,
    positionLabel: '',
    editable: true,
    exportable: true,
    groupable: true,
    navigationItems: () => [],
  },
)
const emit = defineEmits<{
  'update:show': [value: boolean]
  export: [product: LibraryProduct]
  group: [product: LibraryProduct]
  save: [draft: ProductEditDraft]
  retry: []
  navigate: [direction: 'previous' | 'next']
  'navigate-to': [id: string]
}>()
const message = useMessage()
const dialog = useDialog()
const detailTab = ref('sku')
const imageRetries = ref<Record<string, number>>({})
const imageFallbacks = ref<Record<string, boolean>>({})
function retryImage(key: string) { imageRetries.value[key] = (imageRetries.value[key] ?? 0) + 1 }
function imageSource(key: string, source: string) { return imageFallbacks.value[key] ? source : previewImageUrl(source) }
function fallbackImage(key: string, source: string) {
  if (!imageFallbacks.value[key] && previewImageUrl(source) !== source) imageFallbacks.value[key] = true
}
watch(() => props.product?.id, () => { imageRetries.value = {}; imageFallbacks.value = {} })
const editing = ref(false)
const editDraft = ref<ProductEditDraft | null>(null)
const editBaseline = ref<ProductEditDraft | null>(null)
const validationMessage = ref<string | null>(null)

type EditableSku = ProductEditDraft['skus'][number]
type EditableAttribute = ProductEditDraft['attributes'][number]
let draftSkuSequence = 0

function draftFromProduct(product: LibraryProduct): ProductEditDraft {
  return {
    title: product.title,
    attributes: product.attributes.map((attribute) => ({ ...attribute })),
    specDimensions: product.specDimensions.map((dimension) => ({
      ...dimension,
    })),
    skus: product.skus.map((sku) => ({
      draftKey: sku.draftKey,
      sourceSkuId: sku.sourceSkuId,
      name: sku.name,
      currentPrice: sku.currentPrice,
      imageUrl: sku.imageUrl,
      specValues: { ...sku.specValues },
    })),
  }
}

function cloneDraft(draft: ProductEditDraft): ProductEditDraft {
  return {
    title: draft.title,
    attributes: draft.attributes.map((attribute) => ({ ...attribute })),
    specDimensions: draft.specDimensions.map((dimension) => ({
      ...dimension,
    })),
    skus: draft.skus.map((sku) => ({
      draftKey: sku.draftKey,
      sourceSkuId: sku.sourceSkuId,
      name: sku.name,
      currentPrice: sku.currentPrice,
      imageUrl: sku.imageUrl,
      specValues: { ...sku.specValues },
    })),
  }
}

watch(
  () => props.product,
  (product) => {
    if (!product) {
      editing.value = false
      editDraft.value = null
      editBaseline.value = null
      validationMessage.value = null
      return
    }
    const next = draftFromProduct(product)
    editDraft.value = cloneDraft(next)
    editBaseline.value = next
    editing.value = props.editable
    validationMessage.value = null
    detailTab.value = 'sku'
  },
  { immediate: true },
)

const hasUnsavedChanges = computed(
  () =>
    editing.value &&
    JSON.stringify(editDraft.value) !== JSON.stringify(editBaseline.value),
)

function startEditing() {
  if (!props.product || !props.editable) return
  const next = draftFromProduct(props.product)
  editDraft.value = cloneDraft(next)
  editBaseline.value = next
  validationMessage.value = null
  editing.value = true
  detailTab.value = 'sku'
}

function cancelEditing() {
  if (!editBaseline.value) return
  editDraft.value = cloneDraft(editBaseline.value)
  validationMessage.value = null
  editing.value = false
}

function closeImmediately() {
  editing.value = false
  validationMessage.value = null
  emit('update:show', false)
}

function requestClose() {
  if (!hasUnsavedChanges.value) {
    closeImmediately()
    return
  }
  dialog.warning({
    title: '放弃未保存的修改？',
    content: '商品资料草稿尚未保存，关闭后本次修改不会写入演示商品库。',
    positiveText: '放弃修改',
    negativeText: '继续编辑',
    onPositiveClick: closeImmediately,
  })
}

function navigateImmediately(direction: 'previous' | 'next') {
  editing.value = false
  validationMessage.value = null
  emit('navigate', direction)
}

function navigateToImmediately(id: string) {
  editing.value = false
  validationMessage.value = null
  emit('navigate-to', id)
}

function requestNavigate(direction: 'previous' | 'next') {
  if (!hasUnsavedChanges.value) {
    navigateImmediately(direction)
    return
  }
  dialog.warning({
    title: '放弃未保存的修改并切换商品？',
    content: '当前商品资料草稿尚未保存，切换后本次修改不会写入演示商品库。',
    positiveText: '放弃并切换',
    negativeText: '继续编辑',
    onPositiveClick: () => navigateImmediately(direction),
  })
}

function requestNavigateTo(id: string) {
  if (id === props.product?.id) return
  if (!hasUnsavedChanges.value) {
    navigateToImmediately(id)
    return
  }
  dialog.warning({
    title: '放弃未保存的修改并切换商品？',
    content: '当前商品资料草稿尚未保存，切换后本次修改不会写入演示商品库。',
    positiveText: '放弃并切换',
    negativeText: '继续编辑',
    onPositiveClick: () => navigateToImmediately(id),
  })
}

function validateDraft(draft: ProductEditDraft): string | null {
  if (!draft.title.trim()) return '商品标题不能为空'
  const attributeNames = draft.attributes.map((item) => item.name.trim())
  if (attributeNames.some((name) => !name)) return '商品属性名称不能为空'
  if (draft.attributes.some((item) => !item.value.trim()))
    return '商品属性值不能为空'
  if (new Set(attributeNames).size !== attributeNames.length)
    return '商品属性名称不能重复'

  const dimensionNames = draft.specDimensions.map((item) => item.name.trim())
  if (dimensionNames.some((name) => !name)) return 'SKU 规格维度不能为空'
  if (new Set(dimensionNames).size !== dimensionNames.length)
    return 'SKU 规格维度不能重复'
  for (const sku of draft.skus) {
    if (!sku.name.trim()) return 'SKU 名称不能为空'
    if (
      draft.specDimensions.some(
        (dimension) => !sku.specValues[dimension.id]?.trim(),
      )
    )
      return `SKU「${sku.name || sku.sourceSkuId || '前端新增'}」的规格值不能为空`
    if (
      sku.currentPrice !== null &&
      !/^\d+(?:\.\d{1,2})?$/.test(sku.currentPrice.trim())
    )
      return `SKU「${sku.name}」的当前价格应为非负数字，未知请留空`
  }
  return null
}

function saveEditing() {
  if (!editDraft.value || props.saving) return
  for (const sku of editDraft.value.skus)
    if (sku.currentPrice !== null && !sku.currentPrice.trim())
      sku.currentPrice = null
  validationMessage.value = validateDraft(editDraft.value)
  if (validationMessage.value) return
  emit('save', cloneDraft(editDraft.value))
}

function allocateDraftSkuKey(): string {
  const keys = new Set(editDraft.value?.skus.map((sku) => sku.draftKey) ?? [])
  let key = ''
  do key = `draft-sku-${++draftSkuSequence}`
  while (keys.has(key))
  return key
}

function addSku() {
  if (!editDraft.value) return
  const sku: ProductEditSku = {
    draftKey: allocateDraftSkuKey(),
    sourceSkuId: null,
    name: `新增 SKU ${editDraft.value.skus.length + 1}`,
    currentPrice: null,
    imageUrl: null,
    specValues: Object.fromEntries(
      editDraft.value.specDimensions.map((dimension) => [dimension.id, '']),
    ),
  }
  editDraft.value.skus.push(sku)
  validationMessage.value = null
}

function removeSku(draftKey: string) {
  if (!editDraft.value) return
  editDraft.value.skus = editDraft.value.skus.filter(
    (sku) => sku.draftKey !== draftKey,
  )
  validationMessage.value = null
}

function sourceSku(draftKey: string): ProductSku | undefined {
  return props.product?.skus.find((sku) => sku.draftKey === draftKey)
}

function formatSkuSpecs(sku: ProductSku): string {
  const dimensions = props.product?.specDimensions ?? []
  return dimensions
    .map(
      (dimension) =>
        `${dimension.name}：${sku.specValues[dimension.id] || '—'}`,
    )
    .join(' · ')
}

const attributeEditColumns = computed<DataTableColumns<EditableAttribute>>(
  () => [
    {
      title: '属性名称',
      key: 'name',
      width: 220,
      render: (row, index) =>
        h(AppInput, {
          modelValue: row.name,
          ariaLabel: `属性 ${index + 1} 名称`,
          'onUpdate:modelValue': (value: string) => {
            row.name = value
          },
        }),
    },
    {
      title: '属性值',
      key: 'value',
      render: (row, index) =>
        h(AppInput, {
          modelValue: row.value,
          ariaLabel: `属性 ${index + 1} 值`,
          'onUpdate:modelValue': (value: string) => {
            row.value = value
          },
        }),
    },
  ],
)

const skuEditColumns = computed<DataTableColumns<EditableSku>>(() => {
  const dimensions = editDraft.value?.specDimensions ?? []
  return [
    {
      title: 'SKU 源 ID',
      key: 'sourceSkuId',
      width: 190,
      render: (row) => {
        const sourceSkuId = row.sourceSkuId
        return sourceSkuId
          ? h(NTooltip, null, {
              trigger: () => h('span', sourceSkuId),
              default: () => sourceSkuId,
            })
          : h(NText, { depth: 3 }, () => '前端新增（无平台源 ID）')
      },
    },
    {
      title: 'SKU 名称',
      key: 'name',
      width: 150,
      render: (row) =>
        h(AppInput, {
          modelValue: row.name,
          ariaLabel: `${row.draftKey} SKU 名称`,
          'onUpdate:modelValue': (value: string) => {
            row.name = value
          },
        }),
    },
    ...dimensions.map((dimension) => ({
      title: dimension.name || '未命名规格',
      key: `spec-${dimension.id}`,
      width: 140,
      render: (row: EditableSku) =>
        h(AppInput, {
          modelValue: row.specValues[dimension.id] ?? '',
          ariaLabel: `${row.draftKey} ${dimension.name || '规格'}值`,
          'onUpdate:modelValue': (value: string) => {
            row.specValues[dimension.id] = value
          },
        }),
    })),
    {
      title: '当前价格',
      key: 'currentPrice',
      width: 130,
      render: (row) =>
        h(AppInput, {
          modelValue: row.currentPrice,
          placeholder: '未知留空',
          ariaLabel: `${row.draftKey} 当前价格`,
          'onUpdate:modelValue': (value: string) => {
            row.currentPrice = value
          },
        }),
    },
    {
      title: '采集库存',
      key: 'stockLabel',
      width: 150,
      render: (row) => sourceSku(row.draftKey)?.stockLabel ?? '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 84,
      fixed: 'right',
      render: (row) =>
        h(
          AppButton,
          {
            size: 'small',
            tone: 'danger',
            'aria-label': `删除 SKU ${row.name}`,
            onClick: () => removeSku(row.draftKey),
          },
          () => '删除',
        ),
    },
  ]
})

const imageSections = computed(() => {
  const product = props.product
  if (!product) return []
  const displayedSkus =
    editing.value && editDraft.value ? editDraft.value.skus : product.skus
  return [
    {
      key: 'main',
      label: '主图',
      images: (
        product.previewMainImageUrls ??
        (product.mainImageUrl ? [product.mainImageUrl] : [])
      ).map((src, index) => ({
        src,
        label: `主图 ${index + 1}`,
        caption: '',
        skuKey: undefined,
      })),
    },
    {
      key: 'sku',
      label: 'SKU 图',
      images: displayedSkus.map((sku) => ({
        src: sku.imageUrl,
        label: sku.name,
        caption: sku.sourceSkuId ?? '前端新增（无平台源 ID）',
        skuKey: sku.draftKey,
      })),
    },
    {
      key: 'detail',
      label: '详情图',
      images: product.detailImageUrls.map((src, index) => ({
        src,
        label: `详情图 ${index + 1}`,
        caption: '',
        skuKey: undefined,
      })),
    },
  ]
})

function replaceImage() {
  message.info('演示模式：图片替换尚未上传或写入商品资料')
}

async function copy(value: string, label: string) {
  try {
    await copyText(value)
    message.success(`${label}已复制`)
  } catch {
    message.error('复制失败，请重试')
  }
}

const basicText = computed(() => {
  const row = props.product
  if (!row) return ''
  return [
    `商品标题：${row.title}`,
    `商品 ID：${row.productId}`,
    `来源平台：${row.platform}`,
    `完整类目：${row.category ?? '—'}`,
    `当前价格：${row.currentPrice === null ? '—' : `¥${row.currentPrice}`}`,
    `商品分组：${row.groupName ?? '未分组'}`,
    `采集时间：${row.collectedAt}`,
  ].join('\n')
})

const skuText = computed(() =>
  (props.product?.skus ?? [])
    .map(
      (sku) =>
        `${sku.name}\t${sku.sourceSkuId ?? '前端新增（无平台源 ID）'}\t${sku.currentPrice === null ? '—' : `¥${sku.currentPrice}`}\t${sku.stockLabel ?? '—'}`,
    )
    .join('\n'),
)

const allText = computed(() => {
  const row = props.product
  if (!row) return ''
  return [
    basicText.value,
    '',
    'SKU：',
    skuText.value,
    '',
    '属性：',
    ...row.attributes.map((item) => `${item.name}：${item.value}`),
  ].join('\n')
})
</script>

<template>
  <AppDialog
    :show="show"
    :title="editable ? '编辑商品' : '商品详情'"
    size="workspace"
    :content-scrollable="false"
    positive-text="关闭"
    :show-negative="false"
    @update:show="!$event && requestClose()"
    @confirm="requestClose"
  >
    <template #footer-start>
      <div v-if="editing && editable" class="product-preview__footer-actions">
        <AppButton :disabled="saving" @click="cancelEditing">
          取消编辑
        </AppButton>
        <AppButton tone="primary" :loading="saving" @click="saveEditing">
          保存编辑
        </AppButton>
      </div>
    </template>
    <ErrorState v-if="error" :description="error" retryable @retry="emit('retry')" />
    <LoadingState v-else-if="!product" />
    <template v-else>
      <div class="product-preview__layout" :aria-busy="loading">
        <div v-if="loading" class="product-preview__loading-mask" role="status" aria-label="加载中"><NSpin size="small" /></div>
        <ProductRangeNavigator :items="navigationItems" :selected-id="product.id" :position-label="positionLabel"
          :can-previous="canPrevious" :can-next="canNext" :disabled="loading"
          @navigate="requestNavigate" @navigate-to="requestNavigateTo" />
        <div class="product-preview__content" :inert="loading || undefined">
          <section class="product-preview__summary">
            <div class="product-preview__summary-heading">
              <div class="product-preview__summary-title">
                <NForm
                  v-if="editing && editable && editDraft"
                  label-placement="top"
                >
                  <NFormItem label="商品标题" required>
                    <AppInput
                      v-model="editDraft.title"
                      aria-label="编辑商品标题"
                      :maxlength="120"
                    />
                  </NFormItem>
                </NForm>
                <h3 v-else>{{ product.title }}</h3>
                <div class="product-preview__summary-meta">
                  <PlatformDisplay v-if="product.platform" :code="product.platform" />
                  <span v-else>手动创建</span>
                  <span>商品 ID {{ product.productId }}</span>
                  <span>
                    当前价格
                    {{
                      product.currentPrice === null
                        ? '—'
                        : product.currency &&
                            !['CNY', 'RMB'].includes(product.currency)
                          ? `${product.currency} ${product.currentPrice}`
                          : `¥${product.currentPrice}`
                    }}
                  </span>
                  <span>分组 {{ product.groupName ?? '未分组' }}</span>
                  <StatusTag
                    v-if="product.mockEditedAt"
                    label="演示编辑版"
                    tone="warning"
                  />
                </div>
              </div>
              <div v-if="!editing" class="product-preview__heading-actions">
                <div class="product-preview__copy-actions">
                  <AppButton v-if="editable" @click="startEditing"
                    >编辑商品资料</AppButton
                  >
                  <AppButton
                    size="small"
                    @click="copy(product.title, '商品标题')"
                    >复制标题</AppButton
                  >
                  <AppButton size="small" @click="copy(basicText, '基础信息')"
                    >复制基础信息</AppButton
                  >
                  <AppButton
                    size="small"
                    :disabled="!groupable"
                    :title="groupable ? undefined : '正式分组写入尚未接入'"
                    @click="$emit('group', product)"
                    >移动分组</AppButton
                  >
                  <AppButton
                    tone="primary"
                    size="small"
                    :disabled="!exportable"
                    :title="exportable ? undefined : '正式导出尚未接入'"
                    @click="$emit('export', product)"
                  >
                    导出商品数据包
                  </AppButton>
                </div>
              </div>
            </div>

            <NAlert v-if="validationMessage" type="error">
              {{ validationMessage }}
            </NAlert>

            <NDescriptions bordered :column="3" label-placement="left">
              <NDescriptionsItem label="店铺">{{ product.shopName || '—' }}</NDescriptionsItem>
              <NDescriptionsItem label="完整类目" :span="2">
                {{ product.category ?? '—' }}
              </NDescriptionsItem>
              <NDescriptionsItem label="采集时间">
                {{ product.collectedAt }}
              </NDescriptionsItem>
              <NDescriptionsItem label="SKU 数量">{{ product.skuCount ?? product.skus.length }}</NDescriptionsItem>
              <NDescriptionsItem label="图片">
                主图 {{ product.mainImageCount ?? 0 }} · 详情图 {{ product.detailImageCount ?? 0 }} · SKU 图 {{ product.skuImageCount ?? 0 }}
              </NDescriptionsItem>
            </NDescriptions>
          </section>

          <section class="product-preview__image-workspace">
            <article
              v-for="section in imageSections"
              :key="section.key"
              class="product-preview__image-section"
            >
              <header class="product-preview__image-section-header">
                <h4>{{ section.label }}</h4>
                <NText depth="3">{{ section.images.length }} 张</NText>
              </header>
              <NText v-if="!section.images.length" depth="3">—</NText>
              <div v-else class="product-preview__image-strip">
                <div
                  v-for="(image, index) in section.images"
                  :key="image.skuKey ?? `${section.key}:${image.src}:${index}`"
                  class="product-preview__image-card"
                >
                  <div class="product-preview__image-canvas">
                    <NImage
                      v-if="image.src"
                      :key="imageRetries[`${section.key}:${index}`] ?? 0"
                      :src="imageSource(`${section.key}:${index}`, image.src)"
                      :preview-src="image.src"
                      :alt="`${product.title} ${image.label}`"
                      lazy
                      object-fit="contain"
                      :img-props="{
                        referrerpolicy: 'no-referrer',
                      }"
                      @error="fallbackImage(`${section.key}:${index}`, image.src)"
                    >
                      <template #error>
                        <AppButton size="small" @click.stop="retryImage(`${section.key}:${index}`)">重试</AppButton>
                      </template>
                    </NImage>
                    <NText v-else depth="3">尚未绑定图片</NText>
                  </div>
                  <strong>{{ image.label }}</strong>
                  <NTooltip v-if="image.caption">
                    <template #trigger>
                      <NText depth="3" class="product-preview__image-caption">
                        {{ image.caption }}
                      </NText>
                    </template>
                    {{ image.caption }}
                  </NTooltip>
                  <div v-if="editable" class="product-preview__image-actions">
                    <AppButton size="small" @click="replaceImage"
                      >替换</AppButton
                    >
                    <NTooltip>
                      <template #trigger>
                        <span
                          ><AppButton size="small" disabled
                            >AI改图</AppButton
                          ></span
                        >
                      </template>
                      AI 图片编辑尚未接入
                    </NTooltip>
                    <NTooltip>
                      <template #trigger>
                        <span
                          ><AppButton size="small" disabled
                            >AI鉴图</AppButton
                          ></span
                        >
                      </template>
                      AI 鉴图标准尚未接入
                    </NTooltip>
                  </div>
                </div>
              </div>
            </article>
          </section>

          <AppTabs
            v-model="detailTab"
            type="line"
            class="product-preview__tabs"
          >
            <NTabPane name="sku" tab="SKU">
              <template v-if="editing && editable && editDraft">
                <div class="product-preview__detail-actions">
                  <AppButton size="small" @click="addSku">新增 SKU</AppButton>
                </div>
                <NForm
                  class="product-preview__spec-dimensions"
                  label-placement="top"
                >
                  <NFormItem
                    v-for="(dimension, index) in editDraft.specDimensions"
                    :key="dimension.id"
                    :label="`SKU 规格维度 ${index + 1}`"
                    required
                  >
                    <AppInput
                      v-model="dimension.name"
                      :aria-label="`SKU 规格维度 ${index + 1}`"
                    />
                  </NFormItem>
                </NForm>
                <AppTable
                  :columns="skuEditColumns"
                  :data="editDraft.skus"
                  :row-key="(row) => row.draftKey"
                  :scroll-x="900"
                  bordered
                />
              </template>
              <template v-else>
                <div class="product-preview__detail-actions">
                  <AppButton size="small" @click="copy(skuText, 'SKU 信息')"
                    >复制 SKU</AppButton
                  >
                  <AppButton size="small" @click="copy(allText, '全部商品信息')"
                    >复制全部信息</AppButton
                  >
                </div>
                <NList bordered>
                  <NListItem v-for="sku in product.skus" :key="sku.draftKey">
                    <div class="product-preview__sku">
                      <DeferredPreviewThumbnail
                        :src="sku.imageUrl"
                        :title="sku.name"
                      />
                      <div>
                        <strong>{{ sku.name }}</strong
                        ><br />{{
                          sku.sourceSkuId ?? '前端新增（无平台源 ID）'
                        }}
                        <div class="product-preview__sku-specs">
                          {{ formatSkuSpecs(sku) }}
                        </div>
                      </div>
                      <span>{{
                        sku.currentPrice === null ? '—' : `¥${sku.currentPrice}`
                      }}</span>
                      <span>{{ sku.stockLabel ?? '—' }}</span>
                    </div>
                  </NListItem>
                </NList>
                <NText v-if="!product.skus.length" depth="3">—</NText>
              </template>
            </NTabPane>
            <NTabPane name="attributes" tab="商品属性">
              <AppTable
                v-if="editing && editable && editDraft"
                :columns="attributeEditColumns"
                :data="editDraft.attributes"
                bordered
              />
              <NDescriptions v-else bordered :column="2">
                <NDescriptionsItem
                  v-for="item in product.attributes"
                  :key="item.name"
                  :label="item.name"
                >
                  {{ item.value }}
                </NDescriptionsItem>
              </NDescriptions>
              <NText v-if="!product.attributes.length" depth="3">—</NText>
            </NTabPane>
            <NTabPane name="package" tab="资料包">
              <NAlert v-if="product.mockEditedAt" type="info">
                将来导出应读取已保存编辑版；正式 TXT／ZIP 导出尚未接入。
              </NAlert>
              <NList bordered>
                <NListItem
                  v-for="file in product.packageFiles"
                  :key="file.name"
                >
                  {{ file.name }}
                  <template #suffix><StatusTag :label="file.kind" /></template>
                </NListItem>
              </NList>
              <NText v-if="!product.packageFiles.length" depth="3">—</NText>
            </NTabPane>
            <NTabPane name="history" tab="采集历史">
              <NList bordered>
                <NListItem v-for="item in product.history" :key="item.id">
                  {{ item.collectedAt }} · {{ item.summary }}
                  <template #suffix>
                    <StatusTag
                      :label="
                        item.state === 'completed'
                          ? '完成'
                          : item.state === 'partial'
                            ? '部分完成'
                            : '失败'
                      "
                      :tone="
                        item.state === 'completed'
                          ? 'success'
                          : item.state === 'partial'
                            ? 'warning'
                            : 'error'
                      "
                    />
                  </template>
                </NListItem>
              </NList>
              <NText v-if="!product.history.length" depth="3">—</NText>
            </NTabPane>
          </AppTabs>
        </div>

      </div>
    </template>
  </AppDialog>
</template>

<style scoped>
.product-preview__layout {
  position: relative;
  display: grid;
  grid-template-columns: clamp(260px, 20vw, 320px) minmax(0, 1fr);
  align-items: stretch;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.product-preview__loading-mask {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--bg-surface-solid) 55%, transparent);
}

.product-preview__content {
  min-width: 0;
  min-height: 0;
  padding-right: var(--space-1);
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
.product-preview__summary {
  display: grid;
  gap: var(--space-3);
}
.product-preview__summary-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  min-width: 0;
}
.product-preview__summary-title {
  min-width: 0;
  flex: 1;
}
.product-preview__summary-title :deep(.n-form-item) {
  margin-bottom: 0;
}
.product-preview__heading-actions {
  display: grid;
  flex: 0 1 360px;
  justify-items: end;
  gap: var(--space-2);
}
.product-preview__copy-actions,
.product-preview__footer-actions,
.product-preview__inline-value {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.product-preview__summary-heading h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-size-page-title);
  font-weight: var(--font-weight-semibold);
}
.product-preview__summary-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
  margin-top: var(--space-2);
  color: var(--text-secondary);
}
.product-preview__copy-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}
.product-preview__image-workspace {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-4);
}
.product-preview__image-section {
  min-width: 0;
  padding: var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  background: var(--bg-surface);
}
.product-preview__image-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}
.product-preview__image-section-header h4 {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-size-section-title);
  font-weight: var(--font-weight-semibold);
}
.product-preview__image-strip {
  display: flex;
  gap: var(--space-3);
  max-width: 100%;
  padding-bottom: var(--space-1);
  overflow-x: auto;
}
.product-preview__image-card {
  display: grid;
  flex: 0 0 190px;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  background: var(--bg-page);
}
.product-preview__image-canvas {
  display: grid;
  height: 128px;
  place-items: center;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
}
.product-preview__image-canvas :deep(.n-image) {
  width: 128px;
  max-width: 100%;
  height: 128px;
}
.product-preview__image-canvas :deep(img) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.product-preview__image-caption {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.product-preview__image-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  white-space: nowrap;
}
.product-preview__image-actions > span {
  flex: 0 0 auto;
}
.product-preview__detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.product-preview__spec-dimensions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.product-preview__spec-dimensions :deep(.n-form-item) {
  margin-bottom: 0;
}
.product-preview__tabs {
  margin-top: var(--space-5);
}
.product-preview__tabs :deep(.n-alert) {
  margin-bottom: var(--space-3);
}
.product-preview__sku {
  display: grid;
  grid-template-columns: 72px minmax(180px, 1fr) 96px 120px;
  align-items: center;
  gap: var(--space-3);
}
.product-preview__sku > .deferred-preview-thumbnail {
  width: 64px;
  height: 64px;
}
.product-preview__sku-specs {
  margin-top: var(--space-1);
  color: var(--text-secondary);
  font-size: var(--font-size-secondary);
}
@media (max-width: 820px) {
  .product-preview__layout {
    grid-template-columns: minmax(160px, 30%) minmax(0, 1fr);
  }
  .product-preview__summary-heading {
    flex-direction: column;
  }
  .product-preview__copy-actions {
    justify-content: flex-start;
  }
  .product-preview__heading-actions {
    width: 100%;
    justify-items: start;
  }
  .product-preview__sku {
    grid-template-columns: 64px minmax(140px, 1fr);
  }
}

@media (max-width: 560px) {
  .product-preview__layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 180px minmax(0, 1fr);
  }
}
</style>
