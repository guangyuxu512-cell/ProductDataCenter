<script setup lang="ts">
import { NTabs } from 'naive-ui'

withDefaults(
  defineProps<{
    modelValue?: string | number
    type?: 'line' | 'card' | 'bar' | 'segment'
  }>(),
  {
    modelValue: undefined,
    type: 'line',
  },
)

defineEmits<{
  'update:modelValue': [value: string | number]
}>()
</script>

<template>
  <NTabs
    :value="modelValue"
    :type="type"
    size="medium"
    animated
    @update:value="$emit('update:modelValue', $event)"
  >
    <slot />
  </NTabs>
</template>
