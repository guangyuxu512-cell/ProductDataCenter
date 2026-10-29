<script setup lang="ts">
import { computed } from 'vue'

import {
  getPlatformDefinition,
  PLATFORM_ALL_NAV_ITEM,
  type PlatformCode,
} from '../model/registry'

const props = defineProps<{ code: PlatformCode | 'all' }>()

const meta = computed(() =>
  props.code === 'all'
    ? PLATFORM_ALL_NAV_ITEM
    : getPlatformDefinition(props.code),
)
</script>

<template>
  <img
    v-if="meta"
    class="platform-icon"
    :src="meta.icon"
    :alt="code === 'all' ? '全部平台图标' : `${meta.label}平台图标`"
  />
</template>

<style scoped>
.platform-icon {
  width: var(--space-5);
  height: var(--space-5);
  flex: 0 0 auto;
  border-radius: var(--radius-sm);
}
</style>
