<script setup lang="ts">
import { NResult } from 'naive-ui'

import AppButton from '@/shared/ui/AppButton.vue'

withDefaults(
  defineProps<{
    title?: string
    description?: string
    retryable?: boolean
  }>(),
  {
    title: '加载失败',
    description: '暂时无法获取数据，请稍后重试。',
    retryable: false,
  },
)

defineEmits<{ retry: [] }>()
</script>

<template>
  <NResult
    status="error"
    :title="title"
    :description="description"
    class="state-panel"
  >
    <template v-if="retryable || $slots.actions" #footer>
      <slot name="actions">
        <AppButton tone="primary" @click="$emit('retry')">重新加载</AppButton>
      </slot>
    </template>
  </NResult>
</template>

<style scoped>
.state-panel {
  min-height: 112px;
  padding: var(--space-4);
}
</style>
