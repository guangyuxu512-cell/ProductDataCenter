<script setup lang="ts">
import { NConfigProvider } from 'naive-ui'
import { createListDensityTheme } from '@/shared/ui/list-density'
import type { ListDensity } from '@/shared/ui/list-density'

withDefaults(defineProps<{ density?: ListDensity }>(), { density: 'default' })
</script>

<template>
  <div
    class="table-toolbar"
    :class="{ 'table-toolbar--compact': density === 'compact' }"
  >
    <NConfigProvider
      abstract
      :theme-overrides="createListDensityTheme(density)"
    >
      <div class="table-toolbar__leading">
        <slot />
      </div>
      <div class="table-toolbar__actions">
        <slot name="actions" />
      </div>
    </NConfigProvider>
  </div>
</template>

<style scoped>
.table-toolbar,
.table-toolbar__leading,
.table-toolbar__actions {
  display: flex;
  align-items: center;
}

.table-toolbar {
  min-height: var(--control-height-default);
  justify-content: space-between;
  gap: var(--space-4);
}

.table-toolbar__leading,
.table-toolbar__actions {
  gap: var(--space-3);
}

.table-toolbar--compact {
  min-height: var(--list-compact-control-height);
  gap: var(--list-compact-gap);
  font-size: var(--list-compact-font-size);
}

.table-toolbar--compact .table-toolbar__leading,
.table-toolbar--compact .table-toolbar__actions {
  gap: var(--list-compact-gap);
}
</style>
