<script setup lang="ts">
import { NConfigProvider } from 'naive-ui'
import { createListDensityTheme } from '@/shared/ui/list-density'
import type { ListDensity } from '@/shared/ui/list-density'

withDefaults(
  defineProps<{
    title?: string
    description?: string
    surface?: 'card' | 'transparent'
    fill?: boolean
    density?: ListDensity
  }>(),
  {
    title: undefined,
    description: undefined,
    surface: 'card',
    fill: false,
    density: 'default',
  },
)
</script>

<template>
  <section
    class="page-section"
    :class="[
      `page-section--${surface}`,
      {
        'page-section--fill': fill,
        'page-section--compact': density === 'compact',
      },
    ]"
  >
    <NConfigProvider
      abstract
      :theme-overrides="createListDensityTheme(density)"
    >
      <header
        v-if="title || description || $slots.actions"
        class="page-section__header"
      >
        <div>
          <h2 v-if="title">{{ title }}</h2>
          <p v-if="description">{{ description }}</p>
        </div>
        <div v-if="$slots.actions" class="page-section__actions">
          <slot name="actions" />
        </div>
      </header>
      <div class="page-section__content">
        <slot />
      </div>
    </NConfigProvider>
  </section>
</template>

<style scoped>
.page-section {
  min-width: 0;
}

.page-section--fill {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.page-section--fill .page-section__content {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.page-section--card {
  /* Retain the former backdrop-filter stacking boundary without blur. */
  isolation: isolate;
  padding: var(--surface-padding);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  background: var(--bg-surface);
  box-shadow: var(--shadow-card);
}

.page-section--compact {
  font-size: var(--list-compact-font-size);
}

.page-section--card.page-section--compact {
  padding: var(--list-compact-padding);
}

.page-section__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
}

.page-section__header h2 {
  font-size: var(--font-size-section-title);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-compact);
}

.page-section__header p {
  margin-top: var(--space-1);
  color: var(--text-secondary);
  font-size: var(--font-size-secondary);
}

.page-section__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.page-section__content {
  min-width: 0;
}
</style>
