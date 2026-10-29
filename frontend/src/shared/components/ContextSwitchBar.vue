<script setup lang="ts">
import AppButton from '@/shared/ui/AppButton.vue'

export interface ContextSwitchItem {
  key: string
  label: string
  disabled?: boolean
}

export type ContextSwitchBarAppearance = 'framed' | 'bare'

withDefaults(
  defineProps<{
    items: readonly ContextSwitchItem[]
    activeKey: string
    label: string
    appearance?: ContextSwitchBarAppearance
  }>(),
  {
    appearance: 'framed',
  },
)

const emit = defineEmits<{
  select: [key: string]
}>()

function select(item: ContextSwitchItem): void {
  if (!item.disabled) {
    emit('select', item.key)
  }
}
</script>

<template>
  <nav
    :class="['context-switch-bar', `context-switch-bar--${appearance}`]"
    :aria-label="label"
    :data-appearance="appearance"
  >
    <AppButton
      v-for="item in items"
      :key="item.key"
      :tone="activeKey === item.key ? 'secondary' : 'text'"
      :disabled="item.disabled"
      :class="{
        'context-switch-bar__item--active': activeKey === item.key,
      }"
      :aria-pressed="activeKey === item.key"
      :aria-label="item.label"
      @click="select(item)"
    >
      <span class="context-switch-bar__content">
        <slot name="icon" :item="item" :active="activeKey === item.key" />
        <span>{{ item.label }}</span>
      </span>
    </AppButton>
  </nav>
</template>

<style scoped>
.context-switch-bar {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  overflow-x: auto;
}

.context-switch-bar--framed {
  padding: var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  background: var(--bg-surface);
}

.context-switch-bar__content {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.context-switch-bar__item--active {
  color: var(--text-link);
  background: var(--color-primary-soft);
  border-color: var(--color-primary);
}

.context-switch-bar__item--active:hover {
  color: var(--text-link);
  background: var(--color-primary-soft);
  border-color: var(--color-primary-pressed);
}
</style>
