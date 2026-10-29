<script setup lang="ts">
import { NConfigProvider } from 'naive-ui'
import { createListDensityTheme } from '@/shared/ui/list-density'
import type { ListDensity } from '@/shared/ui/list-density'
import AppPagination from '@/shared/ui/AppPagination.vue'
import { STANDARD_PAGE_SIZE_OPTIONS } from '@/shared/ui/pagination'

withDefaults(
  defineProps<{
    page: number
    pageSize: number
    itemCount: number
    pageSizes?: number[]
    density?: ListDensity
  }>(),
  {
    pageSizes: () => [...STANDARD_PAGE_SIZE_OPTIONS],
    density: 'default',
  },
)

defineEmits<{
  'update:page': [value: number]
  'update:pageSize': [value: number]
}>()
</script>

<template>
  <div
    class="pagination-bar"
    :class="{ 'pagination-bar--compact': density === 'compact' }"
  >
    <NConfigProvider
      abstract
      :theme-overrides="createListDensityTheme(density)"
    >
      <span>共 {{ itemCount }} 条</span>
      <AppPagination
        :page="page"
        :page-size="pageSize"
        :item-count="itemCount"
        :page-sizes="pageSizes"
        @update:page="$emit('update:page', $event)"
        @update:page-size="$emit('update:pageSize', $event)"
      />
    </NConfigProvider>
  </div>
</template>

<style scoped>
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  color: var(--text-secondary);
  font-size: var(--font-size-secondary);
}

.pagination-bar--compact {
  gap: var(--list-compact-gap);
  font-size: var(--list-compact-font-size);
}
</style>
