<script setup lang="ts">
import { NInputNumber } from 'naive-ui'

import type { FieldWidth } from './types'

withDefaults(
  defineProps<{
    modelValue?: number | null
    placeholder?: string
    width?: FieldWidth
    min?: number
    max?: number
    step?: number
    disabled?: boolean
    clearable?: boolean
  }>(),
  {
    modelValue: null,
    placeholder: '',
    width: 'full',
    min: undefined,
    max: undefined,
    step: 1,
    disabled: false,
    clearable: false,
  },
)

defineEmits<{
  'update:modelValue': [value: number | null]
}>()
</script>

<template>
  <NInputNumber
    class="app-field"
    :class="`app-field--${width}`"
    size="medium"
    :value="modelValue"
    :placeholder="placeholder"
    :min="min"
    :max="max"
    :step="step"
    :disabled="disabled"
    :clearable="clearable"
    @update:value="$emit('update:modelValue', $event)"
  />
</template>
