<script setup lang="ts">
import { NSpin } from 'naive-ui'

withDefaults(defineProps<{ description?: string }>(), {
  description: '正在加载，请稍候…',
})
</script>

<template>
  <div class="state-panel" role="status">
    <NSpin size="medium" />
    <span>{{ description }}</span>
  </div>
</template>

<style scoped>
.state-panel {
  display: flex;
  min-height: 112px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-3);
  color: var(--text-secondary);
}
</style>
