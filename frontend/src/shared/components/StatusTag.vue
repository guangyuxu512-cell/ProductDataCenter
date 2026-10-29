<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'error'

const props = withDefaults(
  defineProps<{
    label: string
    tone?: StatusTone
    appearance?: 'tag' | 'dot'
  }>(),
  {
    tone: 'neutral',
    appearance: 'tag',
  },
)

const tagType = computed(() =>
  props.tone === 'neutral' ? 'default' : props.tone,
)
</script>

<template>
  <span
    v-if="appearance === 'dot'"
    class="status-tag__dot"
    :class="`status-tag__dot--${tone}`"
    :aria-label="label"
    role="status"
  />
  <NTag v-else :type="tagType" size="small" :bordered="false">{{ label }}</NTag>
</template>

<style scoped>
.status-tag__dot {
  display: block;
  width: var(--space-2);
  height: var(--space-2);
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: transparent;
}

.status-tag__dot--info {
  border-color: var(--status-info);
  background: var(--status-info);
}

.status-tag__dot--success {
  border-color: var(--status-success);
  background: var(--status-success);
}

.status-tag__dot--warning {
  border-color: var(--status-warning);
  background: var(--status-warning);
}

.status-tag__dot--error {
  border-color: var(--status-danger);
  background: var(--status-danger);
}
</style>
