<script setup lang="ts">
import { NText, NTooltip } from 'naive-ui'
import { AppButton } from '@/shared/ui'
import DeferredPreviewThumbnail from './DeferredPreviewThumbnail.vue'

withDefaults(defineProps<{
  items: ReadonlyArray<{ id: string; title: string; subtitle: string; imageUrl: string | null }>
  selectedId: string | null
  positionLabel?: string
  canPrevious?: boolean
  canNext?: boolean
  disabled?: boolean
}>(), { positionLabel: '', canPrevious: false, canNext: false, disabled: false })

defineEmits<{
  navigate: [direction: 'previous' | 'next']
  'navigate-to': [id: string]
}>()
</script>

<template>
  <aside class="product-preview__navigator" :inert="disabled || undefined" aria-label="商品范围列表">
    <header class="product-preview__navigator-header">
      <strong>商品范围</strong><NText v-if="positionLabel" depth="3">{{ positionLabel }}</NText>
    </header>
    <div class="product-preview__navigator-list">
      <AppButton v-for="item in items" :key="item.id" class="product-preview__navigator-item"
        :class="{ 'product-preview__navigator-item--active': item.id === selectedId }"
        tone="text" size="small" block :aria-current="item.id === selectedId ? 'true' : undefined"
        @click="$emit('navigate-to', item.id)">
        <span class="product-preview__navigator-row">
          <span class="product-preview__navigator-thumbnail" aria-hidden="true">
            <DeferredPreviewThumbnail :src="item.imageUrl" :title="item.title" />
          </span>
          <span class="product-preview__navigator-copy">
            <NTooltip><template #trigger><span class="product-preview__navigator-title">{{ item.title }}</span></template>{{ item.title }}</NTooltip>
            <span class="product-preview__navigator-subtitle">{{ item.subtitle }}</span>
          </span>
        </span>
      </AppButton>
    </div>
    <nav class="product-preview__navigation" aria-label="翻页商品导航">
      <AppButton size="small" :disabled="!canPrevious || disabled" @click="$emit('navigate', 'previous')">上一件</AppButton>
      <AppButton size="small" :disabled="!canNext || disabled" @click="$emit('navigate', 'next')">下一件</AppButton>
    </nav>
  </aside>
</template>

<style scoped>
.product-preview__navigator {
  display:grid; grid-template-rows:auto minmax(0,1fr) auto; min-width:0; min-height:0; height:100%;
  gap:var(--space-2); padding:var(--space-3); overflow:hidden; border:1px solid var(--border-subtle);
  border-radius:var(--radius-card); background:var(--bg-surface);
}
.product-preview__navigator-header { display:grid; gap:var(--space-1); min-width:0; }
.product-preview__navigator-list { display:grid; align-content:start; gap:var(--space-1); min-height:0; padding-right:var(--space-1); overflow-y:auto; scrollbar-gutter:stable; }
.product-preview__navigator-item { min-width:0; height:auto; min-height:72px; padding:var(--space-2); border:1px solid transparent; }
.product-preview__navigator-item--active { border-color:var(--border-default); background:var(--color-primary-soft); }
.product-preview__navigator-row { display:grid; grid-template-columns:48px minmax(0,1fr); align-items:center; width:100%; min-width:0; gap:var(--space-3); }
.product-preview__navigator-thumbnail { display:block; width:48px; height:48px; }
.product-preview__navigator-thumbnail :deep(.product-image) { --product-image-size:48px; width:48px; height:48px; }
.product-preview__navigator-copy { display:grid; width:100%; min-width:0; gap:var(--space-1); text-align:left; }
.product-preview__navigator-title,.product-preview__navigator-subtitle { overflow:hidden; text-overflow:ellipsis; }
.product-preview__navigator-title { display:-webkit-box; color:var(--text-primary); line-height:var(--line-height-body); text-align:left; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.product-preview__navigator-subtitle { color:var(--text-secondary); font-size:var(--font-size-secondary); text-align:left; white-space:nowrap; }
.product-preview__navigation { display:flex; align-items:center; justify-content:space-between; gap:var(--space-2); }
</style>
