<script setup lang="ts">
import { computed, ref } from 'vue'
import { NInput, NModal, NSpin, NText, useMessage } from 'naive-ui'
import { AppButton } from '@/shared/ui'
import { APP_OVERLAY_HOST_SELECTOR } from '@/shared/ui/overlay-host'
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
const searches = ref<string[]>([])
const columnCount = computed(() => Math.max(4, columns.value.length))
const selected = computed(() => path.value.at(-1))
let requestId = 0

async function open() {
  show.value = true
  path.value = []
  searches.value = []
  if (columns.value.length) columns.value = [columns.value[0]]
  else await loadRoot(false)
}
function close() { show.value = false; requestId += 1; busy.value = false }

async function loadRoot(refresh: boolean) {
  const request = ++requestId
  busy.value = true; error.value = false
  try {
    const result = await fetchCategoryTree('0', null, refresh)
    if (request !== requestId) return
    columns.value = [result.items]; path.value = []; searches.value = []; shopId.value = result.shopId
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
    path.value = nextPath
    columns.value = columns.value.slice(0, index + 1)
    return
  }
  const request = ++requestId
  busy.value = true
  try {
    const result = await fetchCategoryTree(item.id, shopId.value)
    if (request !== requestId) return
    path.value = nextPath
    searches.value = searches.value.slice(0, index + 1)
    columns.value = [...columns.value.slice(0, index + 1), result.items]
  } catch { if (request === requestId) message.error('读取下级类目失败，请重试') }
  finally { if (request === requestId) busy.value = false }
}

function visibleItems(index: number) {
  const keyword = (searches.value[index] ?? '').trim().toLocaleLowerCase()
  return (columns.value[index] ?? []).filter((item) => item.name.toLocaleLowerCase().includes(keyword))
}
function confirm() {
  if (!selected.value?.isLeaf || !shopId.value || busy.value) return
  emit('select', { id: selected.value.id, path: path.value.map((part) => part.name).join(' → '),
    shopId: shopId.value, levels: [...path.value] })
  close()
}
</script>

<template>
  <NInput :value="label" placeholder="请选择抖店类目" aria-label="抖店类目" readonly :disabled="disabled" @click="open">
    <template #suffix><span aria-hidden="true">⌄</span></template>
  </NInput>
  <NModal :show="show" preset="card" title="选择抖店类目" aria-label="选择抖店类目" class="category-picker" :to="APP_OVERLAY_HOST_SELECTOR"
    :mask-closable="false" @update:show="!$event && close()">
    <div class="category-picker__header"><NText depth="3">选择完整类目后确认；已读取的类目优先使用缓存</NText>
      <AppButton size="small" :loading="busy" @click="loadRoot(true)">更新类目</AppButton>
    </div>
    <div v-if="error" class="category-picker__empty"><NText depth="3">类目读取失败</NText>
      <AppButton size="small" @click="loadRoot(false)">重试</AppButton>
    </div>
    <div v-else class="category-picker__columns" :aria-busy="busy">
      <div v-for="columnNumber in columnCount" :key="columnNumber" class="category-picker__column">
        <NInput v-if="columns[columnNumber - 1]" v-model:value="searches[columnNumber - 1]"
          class="category-picker__search" :placeholder="`搜索第 ${columnNumber} 级类目`" clearable />
        <div class="category-picker__list">
          <button v-for="item in visibleItems(columnNumber - 1)" :key="item.id" type="button" class="category-picker__item"
            :class="{ 'category-picker__item--active': path[columnNumber - 1]?.id === item.id }"
            :disabled="!item.enabled || busy" @click="choose(item, columnNumber - 1)">
            <span>{{ item.name }}</span><span v-if="!item.isLeaf" aria-hidden="true">›</span>
          </button>
          <NText v-if="columns[columnNumber - 1] && !visibleItems(columnNumber - 1).length" depth="3">没有匹配的类目</NText>
        </div>
      </div>
      <NSpin v-if="busy" class="category-picker__spinner" size="small" />
    </div>
    <template #footer>
      <div class="category-picker__footer">
        <span>已选：{{ path.map((item) => item.name).join(' → ') || '请选择完整类目' }}</span>
        <div class="category-picker__actions"><AppButton @click="close">取消</AppButton>
          <AppButton tone="primary" :disabled="!selected?.isLeaf || busy" @click="confirm">确认</AppButton></div>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.category-picker { width:min(1200px,calc(100vw - 48px)); max-height:calc(100vh - 48px); }
.category-picker__header,.category-picker__footer { display:flex; align-items:center; justify-content:space-between; gap:var(--space-3); }
.category-picker__header { margin-bottom:var(--space-3); }
.category-picker__columns { position:relative; display:flex; height:min(420px,50vh); min-height:220px; overflow-x:auto; border:1px solid var(--border-subtle); }
.category-picker__column { display:flex; flex-direction:column; flex:1 0 25%; min-width:200px; border-right:1px solid var(--border-subtle); }
.category-picker__search { width:calc(100% - 24px); margin:var(--space-3); flex:none; }
.category-picker__list { flex:1; min-height:0; overflow-y:auto; }
.category-picker__item { display:flex; justify-content:space-between; gap:var(--space-2); width:100%; padding:var(--space-2) var(--space-3); text-align:left; border:0; background:transparent; color:var(--text-primary); cursor:pointer; }
.category-picker__item:hover,.category-picker__item--active { background:var(--bg-surface-raised); color:var(--color-primary); }
.category-picker__item:disabled { opacity:.5; cursor:not-allowed; }
.category-picker__empty,.category-picker__actions { display:flex; align-items:center; gap:var(--space-2); }
.category-picker__spinner { position:absolute; right:var(--space-3); bottom:var(--space-3); }
</style>
