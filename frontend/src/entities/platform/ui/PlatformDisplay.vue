<script setup lang="ts">
import { computed } from 'vue'

import { getPlatformDefinition, type PlatformCode } from '../model/registry'
import PlatformIcon from './PlatformIcon.vue'

const props = withDefaults(
  defineProps<{
    code: PlatformCode
    label?: boolean
    supportLabel?: string
  }>(),
  { label: true, supportLabel: undefined },
)

const meta = computed(() => getPlatformDefinition(props.code))
</script>

<template>
  <span
    v-if="meta"
    class="platform-display"
    :class="{ 'platform-display--with-label': label }"
  >
    <span class="platform-display__icon-slot" aria-hidden="true">
      <PlatformIcon :code="code" />
    </span>
    <span v-if="label" class="platform-display__label">{{ meta.label }}</span>
    <span v-if="supportLabel" class="platform-display__support">
      {{ supportLabel }}
    </span>
  </span>
</template>

<style scoped>
.platform-display {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  line-height: var(--line-height-compact);
  vertical-align: middle;
  white-space: nowrap;
}

.platform-display--with-label {
  width: calc(var(--space-5) + var(--space-2) + 3em);
}

.platform-display__icon-slot {
  display: inline-grid;
  width: var(--space-5);
  height: var(--space-5);
  flex: 0 0 var(--space-5);
  place-items: center;
}

.platform-display__label {
  min-width: 0;
  text-align: left;
}

.platform-display--with-label .platform-display__label {
  flex: 0 0 3em;
}

.platform-display__support {
  color: var(--text-tertiary);
  font-size: var(--font-size-secondary);
}
</style>
