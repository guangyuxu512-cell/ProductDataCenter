<script setup lang="ts">
import { ref } from 'vue'
import { NInput, NPopover, NSpin, NText, useMessage } from 'naive-ui'
import { AppButton } from '@/shared/ui'
import { fetchCategoryTree, type CategoryTreeItem } from '../api/category-lookup'

defineProps<{ label: string; disabled?: boolean }>()
const emit = defineEmits<{ select: [value: { id: string; path: string; shopId: string; levels: CategoryTreeItem[] }] }>()
const message = useMessage()
const show = ref(false)
const busy = ref(false)
const error = ref(false)
const shopId = ref<string | null>(null)
const columns = ref<CategoryTreeItem[][]>([])
const path = ref<CategoryTreeItem[]>([])
let requestId = 0

async function open(value: boolean) {
  show.value = value
  if (!value) { requestId += 1; busy.value = false; return }
  if (!columns.value.length) await loadRoot(false)
}

async function loadRoot(refresh: boolean) {
  const request = ++requestId
  busy.value = true; error.value = false
  try {
    const result = await fetchCategoryTree('0', null, refresh)
    if (request !== requestId) return
    columns.value = [result.items]; path.value = []; shopId.value = result.shopId
  } catch {
    if (request === requestId) {
      if (columns.value.length) message.error('更新失败，仍可使用已缓存的类目')
      else error.value = true
    }
  } finally { if (request === requestId) busy.value = false }
}

async function choose(item: CategoryTreeItem, index: number) {
  if (!item.enabled || busy.value || !shopId.value) return
  const nextPath = [...path.value.slice(0, index), item]
  if (item.isLeaf) {
    emit('select', { id: item.id, path: nextPath.map((part) => part.name).join(' → '),
      shopId: shopId.value, levels: nextPath })
    show.value = false; requestId += 1
    return
  }
  const request = ++requestId
  busy.value = true
  try {
    const result = await fetchCategoryTree(item.id, shopId.value)
    if (request !== requestId) return
    path.value = nextPath
    columns.value = [...columns.value.slice(0, index + 1), result.items]
  } catch { if (request === requestId) message.error('读取下级类目失败，请重试') }
  finally { if (request === requestId) busy.value = false }
}
</script>

<template>
  <NPopover :show="show" trigger="click" placement="bottom-start" @update:show="open">
    <template #trigger>
      <NInput :value="label" placeholder="请选择抖店类目" aria-label="抖店类目" readonly :disabled="disabled">
        <template #suffix><span aria-hidden="true">⌄</span></template>
      </NInput>
    </template>
    <div class="category-picker">
      <div class="category-picker__header"><strong>全部类目</strong>
        <AppButton size="small" :loading="busy" @click="loadRoot(true)">更新类目</AppButton>
      </div>
      <div v-if="error" class="category-picker__empty"><NText depth="3">类目读取失败</NText>
        <AppButton size="small" @click="loadRoot(false)">重试</AppButton>
      </div>
      <div v-else class="category-picker__columns" :aria-busy="busy">
        <div v-for="(items, index) in columns" :key="index" class="category-picker__column">
          <button v-for="item in items" :key="item.id" type="button" class="category-picker__item"
            :class="{ 'category-picker__item--active': path[index]?.id === item.id }"
            :disabled="!item.enabled || busy" @click="choose(item, index)">
            <span>{{ item.name }}</span><span v-if="!item.isLeaf" aria-hidden="true">›</span>
          </button>
          <NText v-if="!items.length" depth="3">没有下级类目</NText>
        </div>
        <NSpin v-if="busy" size="small" />
      </div>
    </div>
  </NPopover>
</template>

<style scoped>
.category-picker { width:min(900px,75vw); max-width:calc(100vw - 36px); }
.category-picker__header { display:flex; align-items:center; justify-content:space-between; padding-bottom:var(--space-2); }
.category-picker__columns { display:flex; min-height:180px; max-height:360px; overflow:auto; border:1px solid var(--border-subtle); }
.category-picker__column { flex:1 0 180px; min-width:0; overflow-y:auto; border-right:1px solid var(--border-subtle); }
.category-picker__item { display:flex; justify-content:space-between; gap:var(--space-2); width:100%; padding:var(--space-2) var(--space-3); text-align:left; border:0; background:transparent; color:var(--text-primary); cursor:pointer; }
.category-picker__item:hover,.category-picker__item--active { background:var(--bg-surface-raised); color:var(--color-primary); }
.category-picker__item:disabled { opacity:.5; cursor:not-allowed; }
.category-picker__empty { display:flex; align-items:center; gap:var(--space-2); }
</style>
