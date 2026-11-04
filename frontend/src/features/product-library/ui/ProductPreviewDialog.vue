<script setup lang="ts">
import { computed, h, nextTick, ref, watch } from 'vue'
import {
  NDropdown, NFormItem, NImage, NImagePreview, NSpin, NSwitch, NTab, NText,
  type DataTableColumns, type SelectOption, type SelectProps, useMessage,
} from 'naive-ui'
import { PlatformDisplay } from '@/entities/platform'
import { ErrorState, LoadingState } from '@/shared/components'
import { AppButton, AppDialog, AppInput, AppSelect, AppTable, AppTabs } from '@/shared/ui'
import { copyText } from '@/shared/utils/copy-text'
import { fetchCategoryAttributes, fetchOriginalCategoryAttributes, predictManualCategory, predictProductCategory,
  type CategoryAttribute, type CategoryTreeItem, type PredictedCategory } from '../api/category-lookup'
import { createManualProduct, fetchEditSnapshot, saveProduct, uploadProductImage, type EditSnapshot, type ProductPatch, type SpecGroup } from '../api/products'
import type { LibraryProduct, ProductSku } from '../model/contracts'
import { previewImageUrl } from '../model/preview-image-url'
import { sourceSpecLayout } from '../model/source-spec-layout'
import { originalAttributeValue, pddAttributeValue } from '../model/source-attributes'
import type { AutoPrecheck, CategoryPrediction, PrecheckIssue } from '../model/precheck'
import DeferredPreviewThumbnail from './DeferredPreviewThumbnail.vue'
import CategoryPicker from './CategoryPicker.vue'
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
  editable?: boolean
  creating?: boolean
  manualSeed?: string
  batchPrediction?: CategoryPrediction
  autoResult?: AutoPrecheck
  precheckPending?: boolean
  precheckRequestError?: string
  focusIssue?: PrecheckIssue | null
  navigationItems?: ReadonlyArray<{ id: string; title: string; subtitle: string; imageUrl: string | null }>
}>(), {
  loading: false, error: null, canPrevious: false, canNext: false,
  positionLabel: '', exportable: true, groupable: true, categoryLookupEnabled: false, editable: false,
  creating: false, manualSeed: '', precheckPending: false, precheckRequestError: '', focusIssue: null,
  navigationItems: () => [],
})
const emit = defineEmits<{
  'update:show': [value: boolean]
  export: [product: LibraryProduct]
  group: [product: LibraryProduct]
  retry: []
  navigate: [direction: 'previous' | 'next']
  'navigate-to': [id: string]
  saved: [id: string]
  created: [id: string]
}>()

const message = useMessage()
const tab = ref('base')
const imageRetries = ref<Record<string, number>>({})
const imageFallbacks = ref<Record<string, boolean>>({})
const categoryBusy = ref(false)
const selectedCategory = ref<string | null>(null)
const categoryLabel = ref('')
const categoryShop = ref<string | null>(null)
const categoryAttributes = ref<CategoryAttribute[]>([])
const categorySchemaLoaded = ref(false)
const categoryError = ref(false)
const predictionBusy = ref(false)
const predictionCandidates = ref<PredictedCategory[]>([])
const predictionShop = ref<string | null>(null)
const predictionMessage = ref('')
const editVersion = ref('')
const editBusy = ref(false)
const saving = ref(false)
const uploading = ref(false)
const uploadInput = ref<HTMLInputElement | null>(null)
const draftTitle = ref('')
const initialTitle = ref('')
const draftMain = ref<string[]>([])
const draftDetail = ref<string[]>([])
const initialMain = ref<string[]>([])
const initialDetail = ref<string[]>([])
const specGroups = ref<SpecGroup[]>([])
const initialSpecGroups = ref<SpecGroup[]>([])
const imageGroupIndex = ref(0)
const specImageEnabled = ref(false)
const specImages = computed(() => specGroups.value[imageGroupIndex.value]?.values ?? [])
function copyGroups(groups: SpecGroup[]) { return groups.map((group) => ({ ...group, values: group.values.map((item) => ({ ...item })) })) }
type SkuDraft = { skuId: string; sourceSpecIds: string[] | null; specIds: string[]; price: string; stock: string; enabled: boolean | null; merchantCode: string; deleted: boolean }
const skuDrafts = ref<SkuDraft[]>([])
const initialSkuDrafts = ref<SkuDraft[]>([])
const selectedParts = ref<CategoryTreeItem[] | null>(null)
const attributeInputs = ref<Record<string, string[]>>({})
const touchedAttributes = ref<string[]>([])
const imagePreviewSource = ref('')
const draggedMainIndex = ref<number | null>(null)
const mainDropIndex = ref<number | null>(null)
let suppressImagePreview = false
let editRequest = 0
const canEdit = computed(() => props.editable && !!editVersion.value && !editBusy.value && !saving.value && !uploading.value)
const dirty = computed(() => !!props.product && (
  draftTitle.value !== initialTitle.value || selectedParts.value !== null || touchedAttributes.value.length > 0 ||
  JSON.stringify(draftMain.value) !== JSON.stringify(initialMain.value) ||
  JSON.stringify(draftDetail.value) !== JSON.stringify(initialDetail.value) ||
  imageGroupIndex.value !== 0 || JSON.stringify(specGroups.value) !== JSON.stringify(initialSpecGroups.value) ||
  JSON.stringify(skuDrafts.value) !== JSON.stringify(initialSkuDrafts.value)))

watch(() => [props.show, props.editable, props.product?.id] as const, () => {
  const request = ++editRequest
  const product = props.product
  editVersion.value = ''; editBusy.value = false; saving.value = false
  selectedParts.value = null; attributeInputs.value = {}; touchedAttributes.value = []
  imagePreviewSource.value = ''; draggedMainIndex.value = null; mainDropIndex.value = null
  specGroups.value = []; initialSpecGroups.value = []; imageGroupIndex.value = 0; specImageEnabled.value = false
  skuDrafts.value = []; initialSkuDrafts.value = []
  if (!props.show || !product) return
  draftTitle.value = product.title; initialTitle.value = product.title
  draftMain.value = [...(product.previewMainImageUrls ?? (product.mainImageUrl ? [product.mainImageUrl] : []))]
  draftDetail.value = [...product.detailImageUrls]
  initialMain.value = [...draftMain.value]; initialDetail.value = [...draftDetail.value]
  if (!props.editable) return
  if (props.creating) {
    const specId = `local-${props.manualSeed}-spec`
    const specImages = [{ id: specId, name: '默认', url: '' }]
    setEditSnapshot({ version: '0'.repeat(64), specImageGroup: '规格', specImages,
      specGroups: [{ index: 0, name: '规格', values: specImages, movable: false }],
      skus: [{ skuId: `local-${props.manualSeed}-sku`, specIds: [specId], price: '', stock: null,
        enabled: false, merchantCode: '' }] })
    return
  }
  editBusy.value = true
  void fetchEditSnapshot(product.id).then((result) => {
    if (request !== editRequest) return
    setEditSnapshot(result)
  }).catch(() => { if (request === editRequest) message.error('读取编辑数据失败，请刷新商品后重试') })
    .finally(() => {
      if (request === editRequest) { editBusy.value = false; applyPddSourceAttributes() }
    })
}, { immediate: true })

function setEditSnapshot(result: EditSnapshot) {
  editVersion.value = result.version
  const groups = result.specGroups?.length ? result.specGroups :
    [{ index: 0, name: result.specImageGroup, values: result.specImages, movable: false }]
  specGroups.value = copyGroups(groups).map((group) => ({ ...group, sourceIndex: group.index }))
  initialSpecGroups.value = copyGroups(specGroups.value)
  imageGroupIndex.value = 0
  specImageEnabled.value = specImages.value.some((item) => !!item.url)
  skuDrafts.value = (result.skus ?? []).map((item) => ({ ...item, sourceSpecIds: [...item.specIds], specIds: [...item.specIds],
    stock: item.stock === null ? '' : String(item.stock), deleted: false }))
  initialSkuDrafts.value = skuDrafts.value.map((item) => ({ ...item, sourceSpecIds: item.sourceSpecIds ? [...item.sourceSpecIds] : null, specIds: [...item.specIds] }))
}

function allowLeave() { return !dirty.value || window.confirm('当前商品有未保存的修改，确定放弃吗？') }
function closeEditor() { if (!saving.value && !uploading.value && allowLeave()) emit('update:show', false) }
function navigateEditor(direction: 'previous' | 'next') { if (!saving.value && !uploading.value && allowLeave()) emit('navigate', direction) }
function navigateTo(id: string) { if (!saving.value && !uploading.value && allowLeave()) emit('navigate-to', id) }

function attributeControl(item: CategoryAttribute) {
  return item.control ?? (item.options.length ? 'single' : 'text')
}
function splitAttributeValue(item: CategoryAttribute, value: string) {
  const text = value.trim()
  if (!text) return []
  return attributeControl(item) === 'multi' ? text.split('、').map((part) => part.trim()).filter(Boolean) : [text]
}
function setAttribute(item: CategoryAttribute, value: string | number | Array<string | number> | null) {
  const raw = Array.isArray(value) ? value : value === null ? [] : [value]
  attributeInputs.value[item.id] = raw.map(String).map((part) => part.trim()).filter(Boolean)
  if (!touchedAttributes.value.includes(item.id)) touchedAttributes.value.push(item.id)
}
function applyPddSourceAttributes() {
  const product = props.product
  if (!props.show || !product || product.platform !== 'pdd' || !canEdit.value || !categorySchemaLoaded.value) return
  const sameTarget = product.targetCategory?.at(-1)?.id === selectedCategory.value && !selectedParts.value
  for (const field of categoryAttributes.value) {
    if (touchedAttributes.value.includes(field.id) ||
        (sameTarget && product.targetAttributes?.some((attribute) => attribute.id === field.id))) continue
    const value = pddAttributeValue(field, categoryAttributes.value, product)
    if (value) setAttribute(field, splitAttributeValue(field, value))
  }
}
function attributeValues(item: CategoryAttribute): string[] {
  if (item.id in attributeInputs.value) return attributeInputs.value[item.id]
  const product = props.product
  if (product?.platform === 'pdd') {
    const current = product.targetCategory?.at(-1)?.id
    if (current && current === selectedCategory.value && !selectedParts.value) {
      return [...(product.targetAttributes?.find((attribute) => attribute.id === item.id)?.values ?? [])]
    }
    return []
  }
  const value = product ? originalAttributeValue(item, categoryAttributes.value, product, selectedCategory.value) : ''
  return splitAttributeValue(item, value)
}
function attributeTextValue(item: CategoryAttribute) {
  return attributeValues(item).join(attributeControl(item) === 'multi' ? '、' : '')
}
function attributeProblem(item: CategoryAttribute): string | null {
  const values = attributeValues(item)
  if (!values.length) return item.required ? '未填写' : null
  if (attributeControl(item) === 'single' && values.length !== 1) return '只能选择一项'
  if (attributeControl(item) === 'number' && values.some((value) => !value.trim() || !Number.isFinite(Number(value)))) return '数字无效'
  if (item.options.length && item.allowCustom !== true && values.some((value) =>
    item.options.filter((option) => option.label === value).length !== 1)) return '包含无效选项'
  return null
}
function attributeOptions(item: CategoryAttribute): SelectOption[] {
  return item.options.map((option) => ({ label: option.label, value: option.label }))
}
function createAttributeOption(label: string): SelectOption {
  return { label: `添加『${label}』`, value: label, __customCreate: true, __customLabel: label }
}
const renderAttributeLabel: SelectProps['renderLabel'] = (option, selected) => {
  const custom = option as SelectOption & { __customCreate?: boolean; __customLabel?: string }
  if (custom.__customCreate && selected) return custom.__customLabel ?? String(custom.value ?? '')
  return String(custom.label ?? custom.value ?? '')
}
const missingAttributes = computed(() => categoryAttributes.value.filter((item) => attributeProblem(item) === '未填写'))
const missingRequired = computed(() => missingAttributes.value.length)
function validImageUrl(value: string) {
  try { return ['http:', 'https:'].includes(new URL(value).protocol) } catch { return false }
}
function specImageIndex(name: string) {
  const matching = specImages.value.flatMap((item, index) => item.name === name ? [index] : [])
  return matching.length === 1 ? matching[0] : -1
}
function setSpecImageGroup(index: number, value: boolean) {
  if (!canEdit.value) return
  if (value && index !== imageGroupIndex.value) {
    if (index !== 0 && !specGroups.value[index]?.movable && !structureDirty.value) return
    const hasOldImages = specGroups.value.some((group, groupIndex) => groupIndex !== index && group.values.some((item) => item.url))
    const note = hasOldImages ? '原规格组的规格图将在保存后移除。' : ''
    if (!window.confirm(`开启后该规格组将置顶展示。${note}`)) return
    for (const [groupIndex, group] of specGroups.value.entries()) {
      if (groupIndex !== index) {
        if (index === 0) for (const item of group.values) {
          item.url = initialSpecGroups.value[group.sourceIndex ?? -1]?.values.find((original) => original.id === item.id)?.url ?? ''
        }
        else for (const item of group.values) item.url = ''
      }
    }
    imageGroupIndex.value = index
    specImageEnabled.value = true
  } else if (index === imageGroupIndex.value) {
    if (!value && specImages.value.some((item) => item.url) &&
        !window.confirm('关闭后将移除当前规格图，保存后生效。确定关闭吗？')) return
    if (!value) for (const item of specImages.value) item.url = ''
    specImageEnabled.value = value
  }
}
function skuDraft(row: ProductSku) { return skuDrafts.value.find((item) => item.skuId === row.draftKey) }
function deleteSku(row: ProductSku) {
  const draft = skuDraft(row)
  if (canEdit.value && draft && window.confirm('确定删除这个 SKU 组合吗？保存后会同步修改商品数据包。')) draft.deleted = true
}
function restoreDeletedSkus() { for (const [index, sku] of skuDrafts.value.entries()) if (!initialSkuDrafts.value[index]?.deleted) sku.deleted = false }
const canStructure = computed(() => canEdit.value && props.product?.platform === 'douyin' &&
  specGroups.value.length > 0 && specGroups.value.every((group) => group.values.length > 0) &&
  skuDrafts.value.length > 0 && skuDrafts.value.every((row) => row.deleted || (row.specIds.length === specGroups.value.length &&
    row.specIds.every((id, index) => specGroups.value[index].values.some((value) => value.id === id)))))
const structureSignature = (groups: SpecGroup[]) => JSON.stringify(groups.map((group) => ({
  sourceIndex: group.sourceIndex, name: group.name, values: group.values.map(({ id, name }) => ({ id, name })),
})))
const structureDirty = computed(() => structureSignature(specGroups.value) !== structureSignature(initialSpecGroups.value) ||
  skuDrafts.value.some((row, index) => !initialSkuDrafts.value[index] ||
    JSON.stringify(row.specIds) !== JSON.stringify(initialSkuDrafts.value[index].specIds)))
const visibleSkus = computed<ProductSku[]>(() => {
  if (!canStructure.value) return (props.product?.skus ?? []).filter((row) => !skuDraft(row)?.deleted)
  return skuDrafts.value.filter((row) => !row.deleted).map((row) => {
    const original = props.product?.skus.find((item) => item.draftKey === row.skuId)
    return { draftKey: row.skuId, sourceSkuId: row.skuId.startsWith('local-') ? null : (original?.sourceSkuId ?? row.skuId),
      name: original?.name ?? '', currentPrice: row.price || null, stockLabel: row.stock || null,
      imageUrl: original?.imageUrl ?? null, specValues: {} }
  })
})
const deletedSkus = computed(() => skuDrafts.value.filter((row, index) => row.deleted && !initialSkuDrafts.value[index]?.deleted).length)

function localId() { return 'local-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12) }
function reindexGroups() { specGroups.value.forEach((group, index) => { group.index = index }) }
function addSpecGroup() {
  if (!canStructure.value || specGroups.value.length >= 3) return
  const name = window.prompt('请输入规格类型名称')?.trim()
  if (!name) return
  const value = window.prompt('请输入“' + name + '”的第一个规格值')?.trim()
  if (!value) return
  const id = localId()
  specGroups.value.push({ index: specGroups.value.length, sourceIndex: null, name, movable: true, values: [{ id, name: value, url: '' }] })
  for (const row of skuDrafts.value) row.specIds.push(id)
}
function addSpecValue(index: number) {
  if (!canStructure.value) return
  const group = specGroups.value[index]
  const name = window.prompt('请输入“' + group.name + '”的规格值')?.trim()
  if (!name) return
  if (group.values.some((value) => value.name === name)) { message.error('规格值不能重复'); return }
  const id = localId()
  const added = new Map<string, string[]>()
  for (const row of skuDrafts.value.filter((item) => !item.deleted)) {
    const ids = [...row.specIds]; ids[index] = id
    added.set(JSON.stringify(ids), ids)
  }
  if (skuDrafts.value.filter((row) => !row.deleted).length + added.size > 2000) { message.error('SKU 组合不能超过 2000 个'); return }
  group.values.push({ id, name, url: '' })
  for (const ids of added.values()) skuDrafts.value.push({ skuId: localId(), sourceSpecIds: null, specIds: ids,
    price: '', stock: '0', merchantCode: '', enabled: true, deleted: false })
}
function deleteSpecValue(index: number, id: string) {
  if (!canStructure.value) return
  const group = specGroups.value[index]
  if (group.values.length <= 1) { message.error('每个规格类型至少保留一个规格值'); return }
  const affected = skuDrafts.value.filter((row) => !row.deleted && row.specIds[index] === id)
  if (affected.length === visibleSkus.value.length) { message.error('至少需要保留一个 SKU 组合'); return }
  if (!window.confirm('删除该规格值会同时删除 ' + affected.length + ' 个 SKU，保存后生效。确定删除吗？')) return
  group.values = group.values.filter((item) => item.id !== id)
  for (const row of affected) row.deleted = true
}
function deleteSpecGroup(index: number) {
  if (!canStructure.value || specGroups.value.length <= 1) return
  const active = skuDrafts.value.filter((row) => !row.deleted)
  const keys = active.map((row) => JSON.stringify(row.specIds.filter((_, i) => i !== index)))
  if (new Set(keys).size !== keys.length) { message.error('删除后部分 SKU 会重复，请先删除多余的 SKU 组合'); return }
  if (!window.confirm('确定删除该规格类型吗？相关 SKU 将同步调整。')) return
  specGroups.value.splice(index, 1)
  for (const row of skuDrafts.value) row.specIds.splice(index, 1)
  if (imageGroupIndex.value === index) { imageGroupIndex.value = 0; specImageEnabled.value = false }
  else if (imageGroupIndex.value > index) imageGroupIndex.value--
  reindexGroups()
}
function moveSpecGroup(index: number, offset: number) {
  if (!canStructure.value) return
  const target = index + offset
  if (target < 0 || target >= specGroups.value.length) return
  if (specImageEnabled.value && (index === imageGroupIndex.value || target === imageGroupIndex.value)) {
    message.warning('带规格图的类型需要排在第一位'); return
  }
  ;[specGroups.value[index], specGroups.value[target]] = [specGroups.value[target], specGroups.value[index]]
  for (const row of skuDrafts.value) [row.specIds[index], row.specIds[target]] = [row.specIds[target], row.specIds[index]]
  if (!specImageEnabled.value) imageGroupIndex.value = 0
  else if (imageGroupIndex.value === index) imageGroupIndex.value = target
  else if (imageGroupIndex.value === target) imageGroupIndex.value = index
  reindexGroups()
}
function changeImage(kind: 'main' | 'detail' | 'sku', index?: number) {
  if (!canEdit.value) return
  const images = kind === 'main' ? draftMain.value : kind === 'detail' ? draftDetail.value : null
  const original = kind === 'sku' ? specImages.value[index ?? -1]?.url : images?.[index ?? -1]
  const result = window.prompt('请输入图片链接', original ?? '')
  if (result === null) return
  const url = result.trim()
  if (!validImageUrl(url)) { message.error('请输入有效的 HTTP 或 HTTPS 图片链接'); return }
  if (kind === 'sku' && index !== undefined && specImages.value[index]) {
    specImages.value[index].url = url
    specImageEnabled.value = true
  }
  else if (images && index === undefined) images.push(url)
  else if (images && index !== undefined) images[index] = url
}
type UploadTarget = { kind: 'main' | 'detail' | 'sku'; index?: number; skuId?: string; request: number }
let uploadTarget: UploadTarget | null = null
function chooseLocalImage(kind: UploadTarget['kind'], index?: number) {
  if (!canEdit.value) return
  if (kind === 'sku' && props.product?.platform === 'pdd') {
    message.warning('拼多多商品的规格图片编辑尚未接入'); return
  }
  const skuId = kind === 'sku' ? specImages.value[index ?? -1]?.id : undefined
  if (kind === 'sku' && !skuId) return
  uploadTarget = { kind, index, skuId, request: editRequest }
  uploadInput.value?.click()
}
async function receiveLocalImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const target = uploadTarget
  input.value = ''
  uploadTarget = null
  if (!file || !target || !canEdit.value) return
  if (file.size > 15 * 1024 * 1024) { message.error('图片大小不能超过 15 MB'); return }
  uploading.value = true
  try {
    const result = await uploadProductImage(file)
    if (target.request !== editRequest || !props.show) return
    if (!validImageUrl(result.url)) throw new Error('图片地址无效，请重试')
    if (target.kind === 'sku') {
      const spec = specImages.value.find((item) => item.id === target.skuId)
      if (spec) { spec.url = result.url; specImageEnabled.value = true }
    } else {
      const images = target.kind === 'main' ? draftMain.value : draftDetail.value
      if (target.index === undefined) images.push(result.url)
      else if (target.index < images.length) images[target.index] = result.url
    }
  } catch (error) { message.error(error instanceof Error ? error.message : '图片上传失败，请重试') }
  finally { uploading.value = false }
}
function removeImage(kind: 'main' | 'detail' | 'sku', index: number) {
  if (!canEdit.value) return
  if (kind === 'sku') { if (specImages.value[index]) specImages.value[index].url = ''; return }
  ;(kind === 'main' ? draftMain.value : draftDetail.value).splice(index, 1)
}
function moveImage(kind: 'main' | 'detail', index: number, offset: number) {
  const images = kind === 'main' ? draftMain.value : draftDetail.value
  const next = index + offset
  if (!canEdit.value || next < 0 || next >= images.length) return
  ;[images[index], images[next]] = [images[next], images[index]]
}

function openImagePreview(source: string) {
  if (!source || suppressImagePreview) return
  imagePreviewSource.value = source
}
function closeImagePreview(show: boolean) {
  if (!show) imagePreviewSource.value = ''
}
function beginMainDrag(index: number, event: DragEvent) {
  if (!canEdit.value) { event.preventDefault(); return }
  draggedMainIndex.value = index
  mainDropIndex.value = index
  suppressImagePreview = true
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
function hoverMainDrop(index: number, event: DragEvent) {
  if (draggedMainIndex.value === null || !canEdit.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  mainDropIndex.value = index
}
function dropMainImage(index: number, event: DragEvent) {
  event.preventDefault()
  const from = draggedMainIndex.value
  if (from !== null && from !== index && draftMain.value[from] !== undefined) {
    const next = [...draftMain.value]
    const [moved] = next.splice(from, 1)
    next.splice(index, 0, moved)
    draftMain.value = next
  }
  finishMainDrag()
}
function finishMainDrag() {
  draggedMainIndex.value = null
  mainDropIndex.value = null
  window.setTimeout(() => { suppressImagePreview = false }, 0)
}

async function submitEdit() {
  const product = props.product
  if (!product || !canEdit.value || !dirty.value) return
  if ((props.creating || draftTitle.value !== initialTitle.value) && (titleLength.value > 60 || !draftTitle.value.trim())) {
    message.error('商品标题不能为空，长度不能超过 60'); tab.value = 'base'; return
  }
  const patch: ProductPatch = { expectedVersion: editVersion.value }
  if (props.creating || draftTitle.value !== initialTitle.value) patch.title = draftTitle.value.trim()
  if (selectedParts.value) patch.category = selectedParts.value.map(({ id, name }) => ({ id, name }))
  if (JSON.stringify(draftMain.value) !== JSON.stringify(initialMain.value)) patch.mainImages = [...draftMain.value]
  if (JSON.stringify(draftDetail.value) !== JSON.stringify(initialDetail.value)) patch.detailImages = [...draftDetail.value]
  if (structureDirty.value) {
    if (!canStructure.value) { message.error('规格数据不完整，请刷新商品后重试'); return }
    const names = specGroups.value.map((group) => group.name.replace(/\s*[（(]\d+[）)]\s*$/u, '').trim())
    if (names.some((name) => !name) || new Set(names).size !== names.length) {
      message.error('规格类型名称不能为空或重复'); tab.value = 'sku'; return
    }
    for (const group of specGroups.value) {
      const values = group.values.map((item) => item.name.trim())
      if (values.some((value) => !value) || new Set(values).size !== values.length) {
        message.error('规格值不能为空或重复'); tab.value = 'sku'; return
      }
    }
    const active = skuDrafts.value.filter((item) => !item.deleted)
    if (!active.length) { message.error('至少需要保留一个 SKU'); return }
    for (const item of active) {
      const previous = initialSkuDrafts.value.find((row) => row.skuId === item.skuId)
      if ((!previous || item.price !== previous.price) &&
          (!/^\d+(?:\.\d{1,2})?$/.test(item.price) || Number(item.price) <= 0 || Number(item.price) > 9999999999)) {
        message.error('请填写有效的 SKU 价格，最多两位小数'); tab.value = 'sku'; return
      }
      if ((!previous || item.stock !== previous.stock) && (!/^\d+$/.test(item.stock) || Number(item.stock) > 2147483647)) {
        message.error('SKU 库存必须是非负整数'); tab.value = 'sku'; return
      }
    }
    const order = specGroups.value.map((_, index) => index)
    if (imageGroupIndex.value > 0) { order.splice(imageGroupIndex.value, 1); order.unshift(imageGroupIndex.value) }
    patch.specStructure = {
      groups: order.map((index) => ({ sourceIndex: specGroups.value[index].sourceIndex ?? null,
        name: specGroups.value[index].name.trim(), values: specGroups.value[index].values.map((value) => ({ ...value, name: value.name.trim() })) })),
      skus: active.map((item) => ({ sourceSpecIds: item.sourceSpecIds ? [...item.sourceSpecIds] : null,
        specIds: order.map((index) => item.specIds[index]), price: item.price, stock: item.stock,
        merchantCode: item.merchantCode, enabled: item.enabled })),
    }
  } else {
    if (imageGroupIndex.value !== 0) patch.specImageGroupIndex = imageGroupIndex.value
    const initialImages = initialSpecGroups.value[imageGroupIndex.value]?.values ?? []
    if (JSON.stringify(specImages.value) !== JSON.stringify(initialImages)) patch.specImages = specImages.value
      .filter((item, index) => item.url !== initialImages[index]?.url)
      .map((item) => ({ specId: item.id, url: item.url }))
    const changedSkus: NonNullable<ProductPatch['skus']> = []
    for (const [index, item] of skuDrafts.value.entries()) {
    const previous = initialSkuDrafts.value[index]
    if (!previous || JSON.stringify(item) === JSON.stringify(previous)) continue
    const change: NonNullable<ProductPatch['skus']>[number] = { specIds: [...item.specIds] }
    if (item.deleted) change.delete = true
    else {
      if (item.price !== previous.price) {
        if (!/^\d+(?:\.\d{1,2})?$/.test(item.price) || Number(item.price) <= 0 || Number(item.price) > 9999999999) {
          message.error('SKU 价格必须大于 0，最多两位小数'); tab.value = 'sku'; return
        }
        change.price = item.price
      }
      if (item.stock !== previous.stock) {
        if (!/^\d+$/.test(item.stock) || Number(item.stock) > 2147483647) {
          message.error('SKU 库存必须是非负整数'); tab.value = 'sku'; return
        }
        change.stock = Number(item.stock)
      }
      if (item.merchantCode !== previous.merchantCode) change.merchantCode = item.merchantCode
      if (item.enabled !== previous.enabled && item.enabled !== null) change.enabled = item.enabled
    }
      changedSkus.push(change)
    }
    if (changedSkus.length) patch.skus = changedSkus
  }
  const invalidSelection = touchedAttributes.value.map((id) => categoryAttributes.value.find((item) => item.id === id))
    .find((field) => field && attributeProblem(field) === '包含无效选项')
  if (invalidSelection) {
    message.error(`${invalidSelection.label}不允许自定义值，请从平台选项中选择`)
    tab.value = 'attributes'
    return
  }
  if (touchedAttributes.value.length) patch.attributes = touchedAttributes.value.flatMap((id) => {
    const field = categoryAttributes.value.find((item) => item.id === id)
    if (!field) return []
    const values = attributeInputs.value[id] ?? []
    return [{ id, name: field.label, values: values.map((name) => ({
      name, valueId: field.options.find((option) => option.label === name)?.value ?? '0',
    })) }]
  })
  saving.value = true
  try {
    if (props.creating) {
      const result = await createManualProduct(draftTitle.value.trim(), props.manualSeed, patch)
      message.success('商品已创建')
      emit('created', result.productId)
      return
    }
    const result = await saveProduct(product.id, patch)
    draftTitle.value = draftTitle.value.trim()
    editVersion.value = result.version; initialTitle.value = draftTitle.value
    message.success('商品已保存')
    selectedParts.value = null; touchedAttributes.value = []
    initialMain.value = [...draftMain.value]; initialDetail.value = [...draftDetail.value]
    emit('saved', product.id)
    try {
      const snapshot = await fetchEditSnapshot(product.id)
      if (props.product?.id === product.id) setEditSnapshot(snapshot)
    } catch {
      editVersion.value = ''
      message.warning('已保存，请刷新后继续编辑')
    }
  } catch (error) { message.error(error instanceof Error ? error.message : '保存失败，请重试') }
  finally { saving.value = false }
}
let categoryRequest = 0
let predictionRequest = 0
const isManualProduct = computed(() => props.creating || !!props.product?.id.startsWith('manual:'))
watch(() => [draftTitle.value, draftMain.value[0]] as const, () => {
  if (!isManualProduct.value) return
  predictionRequest += 1
  predictionBusy.value = false; predictionCandidates.value = []; predictionShop.value = null; predictionMessage.value = ''
})
watch(() => [props.show, props.loading, props.categoryLookupEnabled, props.product?.id,
  props.product?.sourceCategoryId, props.product?.targetCategory] as const, () => {
  imageRetries.value = {}
  imageFallbacks.value = {}
  categoryRequest += 1
  predictionRequest += 1
  predictionBusy.value = false; predictionCandidates.value = []; predictionShop.value = null; predictionMessage.value = ''
  selectedCategory.value = null; categoryLabel.value = ''; categoryShop.value = null
  categoryAttributes.value = []; categorySchemaLoaded.value = false; categoryBusy.value = false; categoryError.value = false
  const product = props.product
  if (!props.show || props.loading || !props.categoryLookupEnabled || !product) return
  if (product.platform === 'douyin' && product.sourceCategoryId) {
    selectedCategory.value = product.sourceCategoryId
    categoryLabel.value = product.category || `原类目 ${product.sourceCategoryId}`
  } else if (product.platform === 'pdd' && product.targetCategory?.length) {
    selectedCategory.value = product.targetCategory.at(-1)?.id ?? null
    categoryLabel.value = product.targetCategory.map((part) => part.name).join(' → ')
  } else return
  // The source Douyin category is already known, so show missing fields without
  // requiring the user to discover the attributes tab first.
  if (product.platform === 'douyin' || tab.value === 'attributes') void loadAttributes()
}, { immediate: true })
watch(() => props.show, (show) => { if (!show) tab.value = 'base' })
watch(tab, (value) => { if (value === 'attributes') void loadAttributes() })

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

async function loadAttributes(refresh = false) {
  const product = props.product
  const categoryId = selectedCategory.value
  if (!props.show || props.loading || !props.categoryLookupEnabled || !product || !categoryId ||
      categoryBusy.value || (!refresh && categorySchemaLoaded.value)) return
  const request = ++categoryRequest
  categoryBusy.value = true; categoryError.value = false
  try {
    const result = categoryShop.value
      ? await fetchCategoryAttributes(categoryShop.value, categoryId, isManualProduct.value ? draftTitle.value : product.title, refresh)
      : await fetchOriginalCategoryAttributes(categoryId, isManualProduct.value ? draftTitle.value : product.title, refresh)
    if (request !== categoryRequest) return
    if ('shopId' in result && typeof result.shopId === 'string') categoryShop.value = result.shopId
    categoryAttributes.value = result.attributes; categorySchemaLoaded.value = true
    applyPddSourceAttributes()
  } catch {
    if (request === categoryRequest) {
      if (categorySchemaLoaded.value) message.error('更新属性失败，仍显示之前的属性')
      else categoryError.value = true
    }
  }
  finally { if (request === categoryRequest) categoryBusy.value = false }
}

function selectCategory(value: { id: string; path: string; shopId: string; levels: CategoryTreeItem[] }) {
  categoryRequest += 1
  selectedCategory.value = value.id; categoryLabel.value = value.path; categoryShop.value = value.shopId
  categoryAttributes.value = []; categorySchemaLoaded.value = false; categoryError.value = false; categoryBusy.value = false
  if (props.editable && canEdit.value) {
    const original = props.product?.platform === 'pdd' ? props.product.targetCategory?.at(-1)?.id : props.product?.sourceCategoryId
    selectedParts.value = value.id === original ? null : value.levels
    attributeInputs.value = {}; touchedAttributes.value = []
  }
  void loadAttributes()
}

function choosePrediction(candidate: PredictedCategory) {
  if (!predictionShop.value || candidate.selectable === false) return
  selectCategory({ id: candidate.id, path: candidate.path, shopId: predictionShop.value,
    levels: candidate.levels.map((level, index) => ({ ...level, isLeaf: index === candidate.levels.length - 1, enabled: true })) })
  predictionCandidates.value = []; predictionMessage.value = ''
  tab.value = 'attributes'
  void loadAttributes()
}

let appliedBatchPrediction: CategoryPrediction | undefined
watch(() => [props.show, props.product?.id, props.batchPrediction, editVersion.value, canEdit.value] as const, () => {
  const prediction = props.batchPrediction
  const product = props.product
  if (!props.show) { appliedBatchPrediction = undefined; return }
  if (!prediction || prediction === appliedBatchPrediction || !product || product.platform !== 'pdd' ||
      product.targetCategory?.length || !canEdit.value) return
  if (prediction.sourceVersion !== editVersion.value) {
    appliedBatchPrediction = prediction
    predictionMessage.value = '商品数据已变化，请重新预检'; return
  }
  if (dirty.value) return
  appliedBatchPrediction = prediction
  if (prediction.missing.length) { predictionMessage.value = `请先完善${prediction.missing.join('、')}`; return }
  if (!prediction.candidates.length) { predictionMessage.value = '未找到推荐类目，请手动选择'; return }
  predictionShop.value = prediction.shopId
  predictionCandidates.value = prediction.candidates
  predictionMessage.value = '请选择合适的推荐类目'
})

async function runPrediction() {
  const product = props.product
  const manual = isManualProduct.value
  if (!product || (!manual && product.platform !== 'pdd') || !canEdit.value || predictionBusy.value) return
  if (!manual && dirty.value) { message.warning('请先保存当前修改，再预检类目'); return }
  const title = draftTitle.value
  const mainImage = draftMain.value[0] ?? ''
  const request = ++predictionRequest
  predictionBusy.value = true; predictionCandidates.value = []; predictionShop.value = null; predictionMessage.value = ''
  try {
    const result = manual ? await predictManualCategory(title, mainImage) : await predictProductCategory(product.id)
    if (request !== predictionRequest) return
    if (manual && (title !== draftTitle.value || mainImage !== (draftMain.value[0] ?? ''))) return
    if (!manual && result.sourceVersion !== editVersion.value) { message.warning('商品数据已变化，请刷新后重新预检'); return }
    if (result.missing.length) { predictionMessage.value = `请先完善${result.missing.join('、')}`; return }
    if (!result.candidates.length) { predictionMessage.value = '未找到推荐类目，请手动选择'; return }
    predictionShop.value = result.shopId; predictionCandidates.value = result.candidates
    const recommended = result.candidates.find((candidate) => candidate.id === result.recommendedId && candidate.selectable === true)
    if (recommended && !manual) choosePrediction(recommended)
    else predictionMessage.value = '请选择合适的推荐类目'
  } catch (error) {
    if (request === predictionRequest) predictionMessage.value = error instanceof Error ? error.message : '类目预检失败，请重试'
  } finally { if (request === predictionRequest) predictionBusy.value = false }
}

function skuPriceValid(value: string | null | undefined) {
  const price = String(value ?? '').trim()
  return /^\d+(?:\.\d{1,2})?$/.test(price) && Number(price) > 0 && Number(price) <= 9999999999
}
const draftIssues = computed<PrecheckIssue[]>(() => {
  const product = props.product
  if (!product) return []
  const issues: PrecheckIssue[] = []
  if (!draftTitle.value.trim()) issues.push({ code: 'title_missing', message: '商品标题未填写', tab: 'base', fieldId: 'title' })
  if (!draftMain.value.length) issues.push({ code: 'main_image_missing', message: '商品主图未填写', tab: 'images', fieldId: 'mainImages' })
  const active = skuDrafts.value.filter((item) => !item.deleted)
  if (!active.length) issues.push({ code: 'sku_missing', message: 'SKU 规格未填写', tab: 'sku', fieldId: 'skus' })
  else active.forEach((item, index) => {
    if (!skuPriceValid(item.price)) issues.push({ code: 'sku_price_invalid', message: `第 ${index + 1} 个 SKU 价格无效`,
      tab: 'sku', fieldId: 'price', skuIndex: index, skuId: item.skuId })
  })
  if (props.categoryLookupEnabled && !selectedCategory.value) {
    issues.push({ code: 'category_missing', message: '类目未选择', tab: 'base', fieldId: 'category' })
  }
  if (categorySchemaLoaded.value) for (const field of categoryAttributes.value) {
    const problem = attributeProblem(field)
    if (problem) issues.push({ code: problem === '未填写' ? 'attribute_missing' : 'attribute_invalid',
      message: `${field.label}${problem}`, tab: 'attributes', fieldId: field.id })
  }
  return issues
})
const serverIssues = computed<PrecheckIssue[]>(() => {
  const result = props.autoResult?.result
  if (!result) return []
  return result.issueDetails?.length
    ? result.issueDetails
    : result.issues.map((message) => ({ code: 'precheck_issue', message, tab: 'base' as const }))
})
const localPrecheckMode = computed(() => dirty.value || props.creating || (!props.autoResult && !!editVersion.value))
const displayedPrecheckIssues = computed(() => localPrecheckMode.value ? draftIssues.value : serverIssues.value)
const precheckSummary = computed(() => {
  if (props.precheckPending) return { text: '自动预检：排队中', tone: 'default' as const }
  if (props.precheckRequestError) return { text: `商品已保存；预检请求失败：${props.precheckRequestError}`, tone: 'error' as const }
  if (localPrecheckMode.value) return displayedPrecheckIssues.value.length
    ? { text: `当前草稿待完善：${displayedPrecheckIssues.value.map((item) => item.message).join('；')}`, tone: 'warning' as const }
    : { text: '当前草稿未发现可直接判断的缺项，保存后将自动预检', tone: 'default' as const }
  const record = props.autoResult
  if (!record) return null
  if (record.error) return { text: `自动预检失败：${record.error}`, tone: 'error' as const }
  if (record.state !== 'done') return { text: `自动预检：${record.state === 'running' ? '预检中' : '排队中'}`, tone: 'default' as const }
  return displayedPrecheckIssues.value.length
    ? { text: `自动预检待处理：${displayedPrecheckIssues.value.map((item) => item.message).join('；')}`, tone: 'warning' as const }
    : { text: '自动预检：已通过', tone: 'success' as const }
})

async function focusPrecheckIssue(issue: PrecheckIssue | null | undefined) {
  if (!issue) return
  tab.value = issue.tab
  await nextTick()
  await nextTick()
  const candidates = [...document.querySelectorAll<HTMLElement>('[data-precheck-field]')]
  const target = candidates.find((element) => element.dataset.precheckField === issue.fieldId &&
    (issue.skuIndex === undefined || element.dataset.precheckSkuIndex === String(issue.skuIndex)))
  target?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  const focusable = target?.matches('input,button,[tabindex]') ? target : target?.querySelector<HTMLElement>('input,button,[tabindex]')
  focusable?.focus({ preventScroll: true })
}
watch(() => props.focusIssue, (issue) => { if (props.show && issue) void focusPrecheckIssue(issue) }, { immediate: true })

const imageSections = computed(() => {
  const product = props.product
  if (!product) return []
  return [
    { key: 'main' as const, label: '主图', images: (props.editable ? draftMain.value : (product.previewMainImageUrls ??
      (product.mainImageUrl ? [product.mainImageUrl] : []))).map((src, index) => ({
        src, label: `主图 ${index + 1}`, caption: '', skuKey: undefined,
      })) },
    { key: 'detail' as const, label: '详情图', images: (props.editable ? draftDetail.value : product.detailImageUrls).map((src, index) => ({
      src, label: `详情图 ${index + 1}`, caption: '', skuKey: undefined,
    })) },
    { key: 'sku' as const, label: '规格图', images: props.editable && specImages.value.length
      ? [...specImages.value.map((item) => ({ src: item.url, label: item.name || specGroups.value[imageGroupIndex.value]?.name || '规格图',
        caption: '', skuKey: item.id })), ...(product.previewSkuImageUrls ?? [])
        .filter((url) => imageGroupIndex.value === 0 && !initialSpecGroups.value[0]?.values.some((item) => item.url === url) &&
          !specImages.value.some((item) => item.url === url))
        .map((src, index) => ({ src, label: `其他规格图 ${index + 1}`, caption: '', skuKey: undefined }))]
      : (product.previewSkuImageUrls ??
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
const titleLength = computed(() => Array.from(props.editable ? draftTitle.value : (props.product?.title ?? ''))
  .reduce((sum, character) => sum + ((character.codePointAt(0) ?? 0) > 127 ? 2 : 1), 0))
const specLayout = computed(() => {
  const skus = canStructure.value ? visibleSkus.value : (props.product?.skus ?? [])
  const fallback = sourceSpecLayout(skus)
  const groups = specGroups.value
  if (!groups.length || groups.some((group, index) => group.index !== index || !group.values.length)) return fallback
  const rows: Record<string, string[]> = {}
  for (const row of skus) {
    const ids = skuDraft(row)?.specIds
    if (!ids || ids.length !== groups.length) return fallback
    const values = ids.map((id, index) => groups[index].values.find((item) => item.id === id)?.name)
    if (values.some((value) => value === undefined)) return fallback
    rows[row.draftKey] = values as string[]
  }
  return {
    axes: groups.map((group) => ({ name: group.name.replace(/\s*[（(]\d+[）)]\s*$/u, '').trim() || '规格',
      values: group.values.map((item) => item.name) })),
    rows,
  }
})
const displayAxes = computed(() => {
  const axes = specLayout.value?.axes ?? []
  const order = axes.map((_, index) => index)
  if (imageGroupIndex.value > 0 && imageGroupIndex.value < order.length) {
    order.splice(imageGroupIndex.value, 1)
    order.unshift(imageGroupIndex.value)
  }
  return order.map((index) => ({ axis: axes[index], index }))
})
const skuColumns = computed<DataTableColumns<ProductSku>>(() => {
  const layout = specLayout.value
  const specColumns: DataTableColumns<ProductSku> = layout
    ? displayAxes.value.map(({ axis, index }) => ({ title: axis.name, key: `spec-${index}`, minWidth: 140,
      render: (row: ProductSku) => layout.rows[row.draftKey]?.[index] ?? '—' }))
    : [{ title: '规格', key: 'name', minWidth: 240, render: (row: ProductSku) =>
      h('div', { class: 'product-preview__sku' }, [
        h(DeferredPreviewThumbnail, { src: row.imageUrl, title: row.name }), h('span', row.name || '—'),
      ]) }]
  return [
    ...specColumns,
    { title: '价格', key: 'price', width: 130, render: (row) => {
      const draft = skuDraft(row)
      const index = visibleSkus.value.findIndex((item) => item.draftKey === row.draftKey)
      return h('div', { 'data-precheck-field': 'price', 'data-precheck-sku-index': String(index) }, [
        h(AppInput, { modelValue: draft?.price ?? (row.currentPrice === null ? '' : `¥${row.currentPrice}`),
          disabled: !canEdit.value || !draft, ariaLabel: `第 ${index + 1} 个 SKU 价格`, inputmode: 'decimal',
          'onUpdate:modelValue': (value: string) => { if (draft) draft.price = value } }),
      ])
    } },
    { title: '库存', key: 'stock', width: 120, render: (row) => {
      const draft = skuDraft(row)
      return h(AppInput, { modelValue: draft?.stock ?? row.stockLabel ?? '', disabled: !canEdit.value || !draft,
        ariaLabel: 'SKU 库存', 'onUpdate:modelValue': (value: string) => { if (draft) draft.stock = value } })
    } },
    { title: 'SKU ID', key: 'skuId', minWidth: 170, render: (row) => row.sourceSkuId ?? '—' },
    { title: '商家编码', key: 'merchantCode', width: 150, render: (row) => {
      const draft = skuDraft(row)
      return h(AppInput, { modelValue: draft?.merchantCode ?? '', disabled: !canEdit.value || !draft,
        ariaLabel: 'SKU 商家编码', 'onUpdate:modelValue': (value: string) => { if (draft) draft.merchantCode = value } })
    } },
    { title: 'SKU 状态', key: 'skuStatus', width: 110, render: (row) => {
      const draft = skuDraft(row)
      return draft?.enabled === null || !draft ? '—' : h(NSwitch, { value: draft.enabled, disabled: !canEdit.value,
        'aria-label': 'SKU 上架状态', 'onUpdate:value': (value: boolean) => { draft.enabled = value } })
    } },
    { title: '操作', key: 'actions', width: 80, render: (row) => h(AppButton, {
      tone: 'link', size: 'small', disabled: !canEdit.value || !skuDraft(row), onClick: () => deleteSku(row),
    }, () => '删除') },
  ]
})
</script>

<template>
  <AppDialog :show="show" :title="creating ? '手动新建商品' : '编辑商品'" size="workspace" :content-scrollable="false"
    :close-on-esc="!imagePreviewSource"
    positive-text="保存" negative-text="关闭" :loading="saving" :positive-disabled="!canEdit || !dirty"
    :positive-disabled-reason="!editable ? '商品编辑尚未启用' : null"
    @confirm="submitEdit" @update:show="!$event && closeEditor()">
    <ErrorState v-if="error" :description="error" retryable @retry="emit('retry')" />
    <LoadingState v-else-if="!product" />
    <div v-else class="product-preview__layout" :class="{ 'product-preview__layout--creating': creating }" :aria-busy="loading">
      <input ref="uploadInput" type="file" accept="image/jpeg,image/png,image/gif,image/webp" hidden @change="receiveLocalImage">
      <div v-if="loading" class="product-preview__loading-mask" role="status" aria-label="加载中"><NSpin size="small" /></div>
      <ProductRangeNavigator v-if="!creating" :items="navigationItems" :selected-id="product.id" :position-label="positionLabel"
        :can-previous="canPrevious" :can-next="canNext" :disabled="loading"
        @navigate="navigateEditor" @navigate-to="navigateTo" />
      <section class="product-preview__main" :inert="loading || undefined">
        <header class="product-preview__header">
          <div class="product-preview__meta">
            <PlatformDisplay :code="product.platform" />
            <span v-if="creating || product.id.startsWith('manual:')">手动创建</span>
            <span v-if="!creating">商品 ID {{ product.productId }}</span>
            <span v-if="product.shopName">来源店铺 {{ product.shopName }}</span>
            <span>分组 {{ product.groupName ?? '未分组' }}</span>
            <NText v-if="product.edited" type="warning">已修改</NText>
            <NText v-if="editable && dirty" type="warning">有未保存的修改</NText>
          </div>
          <div v-if="!creating" class="product-preview__actions">
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
        <div v-if="precheckSummary" class="product-preview__missing" role="status">
          <NSpin v-if="autoResult?.state === 'running' && !localPrecheckMode && !precheckPending" size="small" />
          <NText :type="precheckSummary.tone === 'default' ? undefined : precheckSummary.tone">{{ precheckSummary.text }}</NText>
          <AppButton v-if="displayedPrecheckIssues.length" tone="link" size="small"
            @click="focusPrecheckIssue(displayedPrecheckIssues[0])">定位问题</AppButton>
        </div>
        <div class="product-preview__content" :inert="loading || undefined">
          <section v-if="tab === 'base'" class="product-preview__section">
            <NFormItem label="商品标题" required data-precheck-field="title">
              <AppInput :model-value="editable ? draftTitle : product.title" aria-label="商品标题"
                :readonly="!canEdit" @update:model-value="draftTitle = $event" />
              <span class="product-preview__count">{{ titleLength }}/60</span>
              <AppButton size="small" disabled>AI 优化</AppButton>
            </NFormItem>
            <NFormItem label="抖店类目" required data-precheck-field="category">
              <template v-if="categoryLookupEnabled">
                <CategoryPicker :key="product.id" :label="categoryLabel"
                  :disabled="categoryBusy || (editable && (!canEdit || !['douyin', 'pdd'].includes(product.platform)))" @select="selectCategory" />
                <AppButton v-if="(product.platform === 'pdd' || isManualProduct) && editable" size="small" :loading="predictionBusy"
                  :disabled="!canEdit || categoryBusy" @click="runPrediction">预检类目</AppButton>
              </template>
              <template v-else>
                <AppInput model-value="" aria-label="抖店类目" disabled />
                <AppButton size="small" disabled>更换类目</AppButton>
              </template>
            </NFormItem>
            <NText v-if="selectedCategory && !editable" depth="3">当前类目和属性仅供查看，尚未保存</NText>
            <NText v-if="product.category" depth="3">来源类目：{{ product.category }}</NText>
            <NText v-if="predictionMessage" depth="3">{{ predictionMessage }}</NText>
            <div v-if="predictionCandidates.length" class="product-preview__predictions">
              <AppButton v-for="candidate in predictionCandidates" :key="candidate.id" size="small"
                :disabled="candidate.selectable === false" @click="choosePrediction(candidate)">{{ candidate.path }}</AppButton>
            </div>
          </section>
          <section v-if="tab === 'images'" class="product-preview__image-workspace">
            <article v-for="section in imageSections" :key="section.key" class="product-preview__image-section"
              :data-precheck-field="section.key === 'main' ? 'mainImages' : undefined">
              <header class="product-preview__image-section-header">
                <strong>{{ section.label }}</strong>
                <NText v-if="section.key === 'main' && canEdit && section.images.length > 1" depth="3">拖拽缩略图可排序</NText>
                <div v-if="section.key !== 'sku'" class="product-preview__actions">
                  <AppButton size="small" disabled title="AI 改图尚未接入">AI 创作</AppButton>
                  <AppButton size="small" :loading="uploading" :disabled="!canEdit" @click="chooseLocalImage(section.key)">上传本地图片</AppButton>
                  <AppButton size="small" :disabled="!canEdit" @click="changeImage(section.key)">添加图片链接</AppButton>
                </div>
                <AppButton v-else tone="link" size="small" @click="tab = 'sku'">在规格与 SKU 中设置</AppButton>
              </header>
              <div class="product-preview__image-strip">
                <div v-for="(image, index) in section.images" :key="image.skuKey ?? `${section.key}:${image.src}:${index}`"
                  class="product-preview__image-card"
                  :class="{ 'product-preview__image-card--draggable': section.key === 'main' && canEdit,
                    'product-preview__image-card--dragging': section.key === 'main' && draggedMainIndex === index,
                    'product-preview__image-card--drop': section.key === 'main' && mainDropIndex === index && draggedMainIndex !== index }"
                  :draggable="section.key === 'main' && canEdit"
                  :aria-grabbed="section.key === 'main' ? draggedMainIndex === index : undefined"
                  @dragstart="section.key === 'main' && beginMainDrag(index, $event)"
                  @dragover="section.key === 'main' && hoverMainDrop(index, $event)"
                  @drop="section.key === 'main' && dropMainImage(index, $event)"
                  @dragend="section.key === 'main' && finishMainDrag()">
                  <div class="product-preview__image-canvas">
                    <NImage v-if="image.src" :key="imageRetries[`${section.key}:${index}`] ?? 0"
                      :src="imageSource(`${section.key}:${index}`, image.src)" preview-disabled
                      :alt="`${product.title} ${image.label}`" lazy object-fit="contain"
                      :img-props="{ referrerpolicy: 'no-referrer' }"
                      @click="openImagePreview(image.src)"
                      @error="fallbackImage(`${section.key}:${index}`, image.src)">
                      <template #error><AppButton size="small" @click.stop="retryImage(`${section.key}:${index}`)">重试</AppButton></template>
                    </NImage>
                    <NText v-else depth="3">—</NText>
                  </div>
                  <div v-if="section.key !== 'sku'" class="product-preview__image-actions">
                    <AppButton tone="link" size="small" :disabled="!canEdit" @click="chooseLocalImage(section.key, index)">本地替换</AppButton>
                    <AppButton v-if="section.key === 'detail'" tone="link" size="small" :disabled="!canEdit || index === 0" @click="moveImage(section.key, index, -1)">上移</AppButton>
                    <AppButton v-if="section.key === 'detail'" tone="link" size="small" :disabled="!canEdit || index === section.images.length - 1" @click="moveImage(section.key, index, 1)">下移</AppButton>
                    <AppButton tone="link" size="small" :disabled="!canEdit" @click="removeImage(section.key, index)">删除</AppButton>
                  </div>
                  <template v-else>
                    <NText class="product-preview__image-caption">{{ image.label }}</NText>
                    <div class="product-preview__image-actions">
                      <AppButton tone="link" size="small" :disabled="!canEdit || !image.skuKey || product.platform === 'pdd'" @click="chooseLocalImage('sku', index)">上传</AppButton>
                      <AppButton tone="link" size="small" :disabled="!canEdit || !image.skuKey" @click="changeImage('sku', index)">更换</AppButton>
                      <AppButton tone="link" size="small" :disabled="!canEdit || !image.skuKey || !image.src" @click="removeImage('sku', index)">删除</AppButton>
                      <AppButton tone="link" size="small" disabled title="AI 改图尚未接入">AI 改图</AppButton>
                    </div>
                  </template>
                </div>
              </div>
            </article>
          </section>
          <section v-if="tab === 'attributes'" class="product-preview__section">
            <div v-if="selectedCategory" class="product-preview__section-heading"><strong>类目属性</strong>
              <AppButton size="small" :loading="categoryBusy" @click="loadAttributes(true)">更新属性</AppButton>
            </div>
            <NText v-if="categoryLookupEnabled && product.platform === 'douyin' && !product.sourceCategoryId && !selectedCategory" depth="3">原数据包缺少抖店类目 ID，请手动选择类目</NText>
            <NText v-else-if="categoryLookupEnabled && !selectedCategory" depth="3">请先选择抖店类目</NText>
            <NText v-else-if="categoryBusy" depth="3">正在读取类目属性…</NText>
            <div v-else-if="categoryError"><NText depth="3">类目属性读取失败</NText><AppButton size="small" @click="loadAttributes()">重试</AppButton></div>
            <NText v-else-if="categorySchemaLoaded && !categoryAttributes.length" depth="3">当前类目没有可显示的属性</NText>
            <NText v-else-if="categorySchemaLoaded && product.platform === 'douyin' && selectedCategory === product.sourceCategoryId" depth="3">{{ editable ? '已显示原包中可对应的属性，请核对后保存' : '已显示原包中可对应的属性，尚未校验或保存' }}</NText>
            <NText v-else-if="categorySchemaLoaded && product.platform !== 'pdd'" depth="3">当前类目的属性尚未从原包自动对应</NText>
            <NText v-if="editable && categorySchemaLoaded && missingRequired" type="warning">还有 {{ missingRequired }} 项必填属性未填写</NText>
            <div class="product-preview__attributes">
              <NFormItem v-for="item in categoryAttributes" :key="item.id" :label="item.label" :required="item.required"
                :data-precheck-field="item.id">
                <div v-if="editable && item.options.length" class="product-preview__attribute-input">
                  <AppSelect :model-value="attributeControl(item) === 'multi' ? attributeValues(item) : (attributeValues(item)[0] ?? null)"
                    :options="attributeOptions(item)" clearable filterable show-on-focus
                    :multiple="attributeControl(item) === 'multi'" :max-tag-count="2"
                    :tag="item.allowCustom === true" :on-create="item.allowCustom === true ? createAttributeOption : undefined"
                    :render-label="renderAttributeLabel"
                    :disabled="!canEdit || !['douyin', 'pdd'].includes(product.platform)"
                    :placeholder="item.allowCustom === true ? '请选择、搜索或添加自定义值' : '请选择或搜索平台选项'"
                    @update:model-value="setAttribute(item, $event)" @update:values="setAttribute(item, $event)" />
                  <NText v-if="attributeProblem(item) === '包含无效选项'" type="error">该值不是平台允许的选项</NText>
                </div>
                <AppInput v-else :model-value="attributeTextValue(item)" :aria-label="item.label"
                  :inputmode="attributeControl(item) === 'number' ? 'decimal' : undefined"
                  :readonly="!canEdit || !['douyin', 'pdd'].includes(product.platform)" @update:model-value="setAttribute(item, $event)" />
              </NFormItem>
              <NFormItem v-for="item in categorySchemaLoaded ? [] : product.attributes" :key="item.name" :label="item.name">
                <AppInput :model-value="item.value" readonly />
              </NFormItem>
            </div>
          </section>
          <section v-if="tab === 'sku'" class="product-preview__section">
            <div class="product-preview__section-heading"><strong>销售规格</strong>
              <AppButton size="small" :disabled="!canStructure || specGroups.length >= 3" @click="addSpecGroup">添加规格类型</AppButton>
            </div>
            <div v-for="{ axis, index: axisIndex } in displayAxes" :key="axisIndex" class="product-preview__axis">
              <div class="product-preview__axis-heading">
                <AppInput :model-value="axis.name" aria-label="规格类型" :readonly="!canStructure"
                  @update:model-value="specGroups[axisIndex] && (specGroups[axisIndex].name = $event)" />
                <span class="product-preview__status"><NSwitch
                  :value="axisIndex === imageGroupIndex && specImageEnabled"
                  :disabled="!canEdit || !specGroups[axisIndex]?.values.length || (axisIndex !== imageGroupIndex && axisIndex !== 0 && !specGroups[axisIndex]?.movable && !structureDirty)"
                  :aria-label="`${axis.name}规格图开关`" @update:value="setSpecImageGroup(axisIndex, $event)" />添加规格图</span>
                <div class="product-preview__actions">
                  <AppButton tone="link" size="small" :disabled="!canStructure || axisIndex === 0" @click="moveSpecGroup(axisIndex, -1)">上移</AppButton>
                  <AppButton tone="link" size="small" :disabled="!canStructure || axisIndex === specGroups.length - 1" @click="moveSpecGroup(axisIndex, 1)">下移</AppButton>
                  <AppButton tone="link" size="small" :disabled="!canStructure || specGroups.length <= 1" @click="deleteSpecGroup(axisIndex)">删除</AppButton>
                </div>
              </div>
              <div class="product-preview__values">
                <div v-for="(value, valueIndex) in axis.values" :key="specGroups[axisIndex]?.values[valueIndex]?.id ?? valueIndex" class="product-preview__value">
                  <div v-if="editable && axisIndex === imageGroupIndex && specImageEnabled && specImageIndex(value) >= 0"
                    class="product-preview__spec-image">
                    <NImage v-if="specImages[specImageIndex(value)]?.url"
                      :key="imageRetries[`spec:${axisIndex}:${specImageIndex(value)}`] ?? 0"
                      :src="imageSource(`spec:${axisIndex}:${specImageIndex(value)}`, specImages[specImageIndex(value)].url)"
                      preview-disabled :alt="`${value}规格图片`"
                      :img-props="{ referrerpolicy: 'no-referrer' }" object-fit="contain"
                      @click="openImagePreview(specImages[specImageIndex(value)].url)"
                      @error="fallbackImage(`spec:${axisIndex}:${specImageIndex(value)}`, specImages[specImageIndex(value)].url)">
                      <template #error><AppButton size="small" @click.stop="retryImage(`spec:${axisIndex}:${specImageIndex(value)}`)">重试</AppButton></template>
                    </NImage>
                    <button v-else type="button" class="product-preview__spec-image-add" :disabled="!canEdit || product.platform === 'pdd'"
                      :aria-label="`更换${value}规格图片`" @click="changeImage('sku', specImageIndex(value))">＋</button>
                  </div>
                  <AppInput :model-value="value" :aria-label="`${axis.name}规格值`" :readonly="!canStructure"
                    @update:model-value="specGroups[axisIndex]?.values[valueIndex] && (specGroups[axisIndex].values[valueIndex].name = $event)" />
                  <AppButton v-if="editable && axisIndex === imageGroupIndex && specImageEnabled && specImageIndex(value) >= 0 && specImages[specImageIndex(value)]?.url"
                    tone="link" size="small" :disabled="!canEdit" :aria-label="`更换${value}规格图片`"
                    @click="changeImage('sku', specImageIndex(value))">更换</AppButton>
                  <AppButton v-if="editable && axisIndex === imageGroupIndex && specImageEnabled && specImageIndex(value) >= 0"
                    tone="link" size="small" :disabled="!canEdit || product.platform === 'pdd'" :aria-label="`上传${value}规格图片`"
                    @click="chooseLocalImage('sku', specImageIndex(value))">上传</AppButton>
                  <AppButton tone="link" size="small" :disabled="!canStructure" @click="deleteSpecValue(axisIndex, specGroups[axisIndex].values[valueIndex].id)">删除</AppButton>
                </div>
                <AppButton size="small" :disabled="!canStructure" @click="addSpecValue(axisIndex)">添加规格值</AppButton>
              </div>
            </div>
            <div class="product-preview__section-heading"><strong>价格与库存</strong>
              <div class="product-preview__actions"><AppButton size="small" @click="copy(skuText, 'SKU 信息')">复制 SKU</AppButton>
                <AppButton size="small" @click="copy(allText, '全部商品信息')">复制全部信息</AppButton></div>
            </div>
            <div v-if="deletedSkus" class="product-preview__status">已删除 {{ deletedSkus }} 个 SKU，保存后生效
              <AppButton v-if="!structureDirty" tone="link" size="small" @click="restoreDeletedSkus">撤销删除</AppButton>
            </div>
            <AppTable :columns="skuColumns" :data="visibleSkus" :row-key="(row) => row.draftKey" :scroll-x="1000" bordered />
          </section>
        </div>
      </section>
    </div>
  </AppDialog>
  <NImagePreview :show="!!imagePreviewSource" :src="imagePreviewSource" @update:show="closeImagePreview" />
</template>

<style scoped>
.product-preview__attribute-input { display:grid; width:100%; gap:var(--space-1); }
.product-preview__layout { position:relative; display:grid; grid-template-columns:clamp(260px,20vw,320px) minmax(0,1fr); gap:var(--space-4); height:100%; min-height:0; overflow:hidden; }
.product-preview__layout--creating { grid-template-columns:minmax(0,1fr); }
.product-preview__main { display:flex; flex-direction:column; min-width:0; min-height:0; overflow:hidden; }
.product-preview__loading-mask { position:absolute; inset:0; z-index:2; display:grid; place-items:center; background:color-mix(in srgb,var(--bg-surface-solid) 55%,transparent); }
.product-preview__header { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--space-3); padding-bottom:var(--space-3); }
.product-preview__meta,.product-preview__actions { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.product-preview__predictions { display:flex; gap:var(--space-2); flex-wrap:wrap; }
.product-preview__missing { display:flex; align-items:center; gap:var(--space-2); padding:var(--space-2) 0; }
.product-preview__meta { color:var(--text-secondary); font-size:var(--font-size-secondary); }
.product-preview__tabs { flex:0 0 auto; }
.product-preview__content { min-width:0; min-height:0; flex:1; overflow:auto; padding:var(--space-3) var(--space-1) var(--space-3) 0; scrollbar-gutter:stable; }
.product-preview__section,.product-preview__image-workspace { display:grid; grid-template-columns:minmax(0,1fr); min-width:0; gap:var(--space-4); }
.product-preview__section :deep(.n-form-item-feedback-wrapper) { min-height:0; }
.product-preview__section :deep(.n-form-item-blank) { gap:var(--space-2); }
.product-preview__count { white-space:nowrap; color:var(--text-secondary); }
.product-preview__section-heading,.product-preview__image-section-header { display:flex; align-items:center; justify-content:space-between; gap:var(--space-2); flex-wrap:wrap; }
.product-preview__image-section { display:grid; gap:var(--space-2); min-width:0; }
.product-preview__image-strip { display:flex; gap:var(--space-3); overflow-x:auto; padding-bottom:var(--space-2); }
.product-preview__image-card { flex:0 0 168px; min-width:0; padding:var(--space-2); border:1px solid var(--border-subtle); border-radius:var(--radius-card); background:var(--bg-surface-solid); text-align:center; transition:border-color .15s ease,box-shadow .15s ease,opacity .15s ease; }
.product-preview__image-card--draggable { cursor:grab; }
.product-preview__image-card--draggable:active { cursor:grabbing; }
.product-preview__image-card--dragging { opacity:.45; }
.product-preview__image-card--drop { border-color:var(--color-primary); box-shadow:0 0 0 2px var(--color-primary-soft); }
.product-preview__image-card strong,.product-preview__image-caption { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-preview__image-canvas { display:grid; place-items:center; width:100%; height:112px; margin-bottom:var(--space-2); }
.product-preview__image-canvas :deep(img) { width:112px; height:112px; object-fit:contain; }
.product-preview__image-actions { display:flex; min-height:var(--control-height-compact); align-content:flex-start; justify-content:center; gap:var(--space-1) var(--space-2); flex-wrap:wrap; overflow:hidden; }
.product-preview__image-actions > * { flex:0 0 auto; }
.product-preview__attributes { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-3); }
.product-preview__axis { display:grid; gap:var(--space-3); padding:var(--space-3); background:var(--bg-surface-raised); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }
.product-preview__axis-heading,.product-preview__values,.product-preview__value { display:flex; align-items:center; gap:var(--space-2); flex-wrap:wrap; }
.product-preview__axis-heading > :first-child { width:150px; }
.product-preview__axis-heading > .product-preview__actions { margin-left:auto; }
.product-preview__value > :deep(.n-input) { width:140px; }
.product-preview__spec-image { display:grid; place-items:center; width:40px; height:40px; border:1px dashed var(--border-subtle); border-radius:var(--radius-card); }
.product-preview__spec-image :deep(.n-image),.product-preview__spec-image :deep(img) { width:100%; height:100%; object-fit:contain; }
.product-preview__spec-image-add { width:100%; height:100%; padding:0; border:0; background:transparent; cursor:pointer; }
.product-preview__status { display:flex; align-items:center; gap:var(--space-2); color:var(--text-secondary); }
.product-preview__content :deep(.product-preview__sku) { display:flex; align-items:center; gap:var(--space-3); }
.product-preview__content :deep(.product-preview__sku .deferred-preview-thumbnail) { width:64px; height:64px; flex:0 0 64px; }
@media (max-width:820px) { .product-preview__layout { grid-template-columns:minmax(160px,30%) minmax(0,1fr); } .product-preview__header { flex-wrap:wrap; } .product-preview__attributes { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:560px) { .product-preview__layout { grid-template-columns:minmax(0,1fr); grid-template-rows:180px minmax(0,1fr); } }
</style>
