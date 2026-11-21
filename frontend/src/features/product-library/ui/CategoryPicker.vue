<script setup lang="ts">
import { computed, ref } from 'vue'
import { NInput, NModal, NSpin, NText, useMessage } from 'naive-ui'
import { AppButton } from '@/shared/ui'
import { APP_OVERLAY_HOST_SELECTOR } from '@/shared/ui/overlay-host'
import { fetchCategoryAttributes, fetchCategoryTree, searchCategoryCandidates,
  type CategoryCandidate, type CategoryTreeItem } from '../api/category-lookup'

const props = defineProps<{ label: string; disabled?: boolean; title?: string }>()
const emit = defineEmits<{ select: [value: { id: string; path: string; shopId: string; levels: CategoryTreeItem[] }] }>()
const message = useMessage()
const show = ref(false)
const busy = ref(false)
const error = ref(false)
const shopId = ref<string | null>(null)
const columns = ref<CategoryTreeItem[][]>([])
const path = ref<CategoryTreeItem[]>([])
const searches = ref<string[]>([])
const platformResults = ref<CategoryCandidate[]>([])
const platformIndex = ref(-1)
const columnCount = computed(() => Math.max(4, columns.value.length))
const selected = computed(() => path.value.at(-1))
let requestId = 0

function clearPlatformResults() { platformResults.value = []; platformIndex.value = -1 }
async function open() {
  show.value = true
  path.value = []
  searches.value = []
  clearPlatformResults()
  if (columns.value.length) columns.value = [columns.value[0]]
  else await loadRoot(false)
}
function close() { show.value = false; requestId += 1; busy.value = false; clearPlatformResults() }

async function loadRoot(refresh: boolean, selectedShop: string | null = shopId.value) {
  const request = ++requestId
  busy.value = true; error.value = false
  try {
    const result = await fetchCategoryTree('0', selectedShop, refresh)
    if (request !== requestId) return
    columns.value = [result.items]; path.value = []; searches.value = []; shopId.value = result.shopId
    clearPlatformResults()
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
  clearPlatformResults()
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
function updateSearch(index: number, value: string) {
  searches.value[index] = value
  if (path.value.length > index) {
    path.value = path.value.slice(0, index)
    columns.value = columns.value.slice(0, index + 1)
    searches.value = searches.value.slice(0, index + 1)
  }
  clearPlatformResults()
}
function candidateName(candidate: CategoryCandidate, index: number): string | null {
  const parts = candidate.path.split(/\s*(?:>|→)\s*/).map((part) => part.trim()).filter(Boolean)
  const ancestors = path.value.slice(0, index)
  if (parts.length !== index + 1 || ancestors.length !== index ||
      ancestors.some((part, position) => part.name !== parts[position]) ||
      parts[index] !== candidate.name.trim() || !/^[1-9]\d{0,19}$/.test(candidate.id)) return null
  return parts[index]
}
async function searchPlatform(index: number) {
  const keyword = (searches.value[index] ?? '').trim()
  if (!keyword || !shopId.value || busy.value) return
  const request = ++requestId
  busy.value = true; clearPlatformResults()
  try {
    const result = await searchCategoryCandidates(keyword, shopId.value)
    if (request !== requestId || (searches.value[index] ?? '').trim() !== keyword) return
    if (result.shopId !== shopId.value) throw new Error('搜索上下文不一致')
    platformIndex.value = index
    platformResults.value = result.candidates.filter((candidate) => candidateName(candidate, index) !== null &&
      !(columns.value[index] ?? []).some((item) => item.id === candidate.id))
  } catch { if (request === requestId) message.error('搜索类目失败，请重试') }
  finally { if (request === requestId) busy.value = false }
}
async function choosePlatform(candidate: CategoryCandidate, index: number) {
  const name = candidateName(candidate, index)
  if (!name || !shopId.value || busy.value) return
  const request = ++requestId
  busy.value = true
  try {
    // Search results have no leaf flag. Only offer a selection after the
    // platform also returns the form for this exact ID in the same context.
    await fetchCategoryAttributes(shopId.value, candidate.id, props.title || '商品')
    if (request !== requestId || platformIndex.value !== index ||
        !platformResults.value.some((item) => item.id === candidate.id)) return
    path.value = [...path.value.slice(0, index), { id: candidate.id, name, isLeaf: true, enabled: true }]
    columns.value = columns.value.slice(0, index + 1)
  } catch { if (request === requestId) message.error('读取类目属性失败，请重试') }
  finally { if (request === requestId) busy.value = false }
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
    :style="{ width: 'min(960px, calc(100vw - 48px))', maxHeight: 'calc(100vh - 48px)' }"
    :mask-closable="false" @update:show="!$event && close()">
    <div class="category-picker__header"><NText depth="3">选择完整类目后确认；已读取的类目优先使用缓存</NText>
      <AppButton size="small" :loading="busy" @click="loadRoot(true)">更新类目</AppButton>
    </div>
    <div v-if="error" class="category-picker__empty"><NText depth="3">类目读取失败</NText>
      <AppButton size="small" @click="loadRoot(false)">重试</AppButton>
    </div>
    <div v-else class="category-picker__columns" :aria-busy="busy">
      <div v-for="columnNumber in columnCount" :key="columnNumber" class="category-picker__column">
        <NInput v-if="columns[columnNumber - 1]" :value="searches[columnNumber - 1] ?? ''"
          class="category-picker__search" :placeholder="`搜索第 ${columnNumber} 级类目`" :disabled="busy" clearable
          @update:value="updateSearch(columnNumber - 1, $event)" @keyup.enter="searchPlatform(columnNumber - 1)" />
        <div class="category-picker__list">
          <button v-for="item in visibleItems(columnNumber - 1)" :key="item.id" type="button" class="category-picker__item"
            :class="{ 'category-picker__item--active': path[columnNumber - 1]?.id === item.id }"
            :disabled="!item.enabled || busy" :title="item.name" @click="choose(item, columnNumber - 1)">
            <span>{{ item.name }}<small v-if="item.industryStatus === 2" class="category-picker__status"> 当前店铺未开通</small></span>
            <span v-if="!item.isLeaf" aria-hidden="true">›</span>
          </button>
          <button v-for="item in platformIndex === columnNumber - 1 ? platformResults : []" :key="item.id"
            type="button" class="category-picker__item" :disabled="busy" :title="item.path"
            :class="{ 'category-picker__item--active': path[columnNumber - 1]?.id === item.id }"
            @click="choosePlatform(item, columnNumber - 1)">{{ item.name }}</button>
          <AppButton v-if="(searches[columnNumber - 1] ?? '').trim()" size="small" :disabled="busy"
            @click="searchPlatform(columnNumber - 1)">搜索平台类目</AppButton>
          <NText v-if="columns[columnNumber - 1] && !visibleItems(columnNumber - 1).length &&
            (platformIndex !== columnNumber - 1 || !platformResults.length)" depth="3">没有匹配的类目</NText>
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
.category-picker__header,.category-picker__footer { display:flex; align-items:center; justify-content:space-between; gap:var(--space-3); }
.category-picker__header { margin-bottom:var(--space-3); }
.category-picker__columns { position:relative; display:flex; height:min(420px,50vh); min-height:220px; overflow-x:auto; border:1px solid var(--border-subtle); }
.category-picker__column { display:flex; flex-direction:column; flex:0 0 25%; min-width:180px; border-right:1px solid var(--border-subtle); }
.category-picker__search { width:calc(100% - 24px); margin:var(--space-3); flex:none; }
.category-picker__list { flex:1; min-height:0; overflow-y:auto; }
.category-picker__item { display:flex; justify-content:space-between; gap:var(--space-2); width:100%; padding:var(--space-2) var(--space-3); text-align:left; border:0; background:transparent; color:var(--text-primary); cursor:pointer; }
.category-picker__item:hover,.category-picker__item--active { background:var(--bg-surface-raised); color:var(--color-primary); }
.category-picker__item:disabled { opacity:.5; cursor:not-allowed; }
.category-picker__status { color:var(--text-secondary); }
.category-picker__empty,.category-picker__actions { display:flex; align-items:center; gap:var(--space-2); }
.category-picker__spinner { position:absolute; right:var(--space-3); bottom:var(--space-3); }
</style>
