<script setup lang="ts">
import type { ListDensity } from '@/shared/ui/list-density'
import PageSection from './PageSection.vue'

withDefaults(defineProps<{ density?: ListDensity }>(), { density: 'default' })
</script>

<template>
  <PageSection class="management-list-section" :density="density" fill>
    <div
      class="management-list-section__content"
      :class="{
        'management-list-section__content--compact': density === 'compact',
      }"
    >
      <slot />
    </div>
  </PageSection>
</template>

<style scoped>
.management-list-section__content {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: var(--space-4);
}

.management-list-section__content--compact {
  gap: var(--list-compact-gap);
}
</style>
