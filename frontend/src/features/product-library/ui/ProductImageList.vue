<script setup lang="ts">
import { ref, watch } from 'vue'
import { NImage, NText } from 'naive-ui'
import { AppButton } from '@/shared/ui'
import { previewImageUrl } from '../model/preview-image-url'

export interface ProductImageListItem {
  key: string
  src: string
  label: string
  canLocal?: boolean
  canLink?: boolean
  canDelete?: boolean
}

const props = withDefaults(defineProps<{
  items: ProductImageListItem[]
  editable?: boolean
  draggable?: boolean
  uploading?: boolean
}>(), { editable: false, draggable: false, uploading: false })
const emit = defineEmits<{
  preview: [src: string]
  local: [index: number]
  link: [index: number]
  remove: [index: number]
  reorder: [from: number, to: number]
}>()

const retries = ref<Record<string, number>>({})
const fallbacks = ref<Record<string, boolean>>({})
const dragged = ref<number | null>(null)
const drop = ref<number | null>(null)
let suppressPreview = false

watch(() => props.items.map((item) => `${item.key}:${item.src}`).join('|'), () => {
  retries.value = {}; fallbacks.value = {}
})
function source(item: ProductImageListItem) { return fallbacks.value[item.key] ? item.src : previewImageUrl(item.src) }
function fallback(item: ProductImageListItem) {
  if (!fallbacks.value[item.key] && previewImageUrl(item.src) !== item.src) fallbacks.value[item.key] = true
}
function retry(item: ProductImageListItem) { retries.value[item.key] = (retries.value[item.key] ?? 0) + 1 }
function preview(item: ProductImageListItem) {
  if (item.src && !suppressPreview) emit('preview', item.src)
}
function begin(index: number, event: DragEvent) {
  if (!props.editable || !props.draggable) { event.preventDefault(); return }
  dragged.value = index; drop.value = index; suppressPreview = true
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
function hover(index: number, event: DragEvent) {
  if (dragged.value === null) return
  event.preventDefault(); drop.value = index
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}
function finish() {
  dragged.value = null; drop.value = null
  window.setTimeout(() => { suppressPreview = false }, 0)
}
function place(index: number, event: DragEvent) {
  event.preventDefault()
  if (dragged.value !== null && dragged.value !== index) emit('reorder', dragged.value, index)
  finish()
}
</script>

<template>
  <div class="product-image-list">
    <div v-for="(item, index) in items" :key="item.key" class="product-image-list__card"
      :class="{ 'product-image-list__card--draggable': draggable && editable,
        'product-image-list__card--dragging': dragged === index,
        'product-image-list__card--drop': drop === index && dragged !== index }"
      :draggable="draggable && editable" :aria-grabbed="draggable ? dragged === index : undefined"
      @dragstart="begin(index, $event)" @dragover="hover(index, $event)" @drop="place(index, $event)" @dragend="finish">
      <div class="product-image-list__canvas">
        <NImage v-if="item.src" :key="retries[item.key] ?? 0" :src="source(item)" preview-disabled
          :alt="item.label" lazy object-fit="contain" :img-props="{ referrerpolicy: 'no-referrer' }"
          @click="preview(item)" @error="fallback(item)">
          <template #error><AppButton size="small" @click.stop="retry(item)">重试</AppButton></template>
        </NImage>
        <NText v-else depth="3">—</NText>
      </div>
      <NText class="product-image-list__caption">{{ item.label }}</NText>
      <div class="product-image-list__actions">
        <AppButton v-if="item.canLocal" tone="link" size="small" :loading="uploading" :disabled="!editable" @click="emit('local', index)">本地替换</AppButton>
        <AppButton v-if="item.canLink" tone="link" size="small" :disabled="!editable" @click="emit('link', index)">更换链接</AppButton>
        <AppButton v-if="item.canDelete" tone="link" size="small" :disabled="!editable || !item.src" @click="emit('remove', index)">删除</AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.product-image-list { display:flex; gap:var(--space-3); overflow-x:auto; padding-bottom:var(--space-2); }
.product-image-list__card { flex:0 0 168px; min-width:0; padding:var(--space-2); border:1px solid var(--border-subtle); border-radius:var(--radius-card); background:var(--bg-surface-solid); text-align:center; transition:border-color .15s ease,box-shadow .15s ease,opacity .15s ease; }
.product-image-list__card--draggable { cursor:grab; }
.product-image-list__card--draggable:active { cursor:grabbing; }
.product-image-list__card--dragging { opacity:.45; }
.product-image-list__card--drop { border-color:var(--color-primary); box-shadow:0 0 0 2px var(--color-primary-soft); }
.product-image-list__canvas { display:grid; place-items:center; width:100%; height:112px; margin-bottom:var(--space-2); }
.product-image-list__canvas :deep(img) { width:112px; height:112px; object-fit:contain; }
.product-image-list__caption { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-image-list__actions { display:flex; min-height:var(--control-height-compact); align-content:flex-start; justify-content:center; gap:var(--space-1) var(--space-2); flex-wrap:wrap; }
.product-image-list__actions > * { flex:0 0 auto; }
</style>
