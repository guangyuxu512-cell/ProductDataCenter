<script setup lang="ts">
import { NTimePicker } from 'naive-ui'

import type { FieldWidth } from './types'

withDefaults(
  defineProps<{
    modelValue?: number | null
    width?: FieldWidth
    clearable?: boolean
    disabled?: boolean
  }>(),
  {
    modelValue: null,
    width: 'full',
    clearable: true,
    disabled: false,
  },
)

defineEmits<{
  'update:modelValue': [value: number | null]
}>()
</script>

<template>
  <NTimePicker
    class="app-field"
    :class="`app-field--${width}`"
    size="medium"
    :value="modelValue"
    :clearable="clearable"
    :disabled="disabled"
    @update:value="$emit('update:modelValue', $event)"
  />
</template>
