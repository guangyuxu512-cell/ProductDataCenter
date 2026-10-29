<script setup lang="ts">
import type { FieldWidth } from '@/shared/ui/types'

withDefaults(defineProps<{ label?: string; width?: FieldWidth }>(), {
  label: undefined,
  width: 'sm',
})
</script>

<template>
  <label
    class="filter-field"
    :class="[
      `filter-field--${width}`,
      { 'filter-field--labelled': Boolean(label) },
    ]"
  >
    <span v-if="label">{{ label }}</span>
    <slot />
  </label>
</template>

<style scoped>
.filter-field {
  display: flex;
  flex-direction: column;
  color: var(--text-secondary);
  font-size: var(--font-size-secondary);
}

.filter-field--labelled {
  gap: var(--space-1);
}

.filter-field--xs {
  width: var(--field-width-xs);
  flex: 0 0 var(--field-width-xs);
}

.filter-field--sm {
  width: var(--field-width-sm);
  flex: 0 0 var(--field-width-sm);
}

.filter-field--md {
  width: var(--field-width-md);
  flex: 0 0 var(--field-width-md);
}

.filter-field--lg {
  width: var(--field-width-lg);
  flex: 0 0 var(--field-width-lg);
}

.filter-field--xl {
  width: var(--field-width-xl);
  flex: 0 0 var(--field-width-xl);
}

.filter-field--full {
  width: 100%;
  flex: 1 1 100%;
}
</style>
