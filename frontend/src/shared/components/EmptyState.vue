<script setup lang="ts">
import { NEmpty } from 'naive-ui'

withDefaults(defineProps<{ description?: string }>(), {
  description: '暂无数据',
})
</script>

<template>
  <div class="state-panel">
    <NEmpty size="small" :description="description">
      <template v-if="$slots.actions" #extra>
        <slot name="actions" />
      </template>
    </NEmpty>
  </div>
</template>

<style scoped>
.state-panel {
  display: grid;
  min-height: 112px;
  place-items: center;
}
</style>
