<script setup lang="ts">
import { NRadioButton, NRadioGroup } from 'naive-ui'

import type { AppOption, AppOptionValue } from './types'

defineProps<{
  modelValue?: AppOptionValue | null
  options: AppOption[]
  disabled?: boolean
}>()

defineEmits<{
  'update:modelValue': [value: AppOptionValue]
}>()
</script>

<template>
  <NRadioGroup
    :value="modelValue"
    :disabled="disabled"
    size="medium"
    @update:value="$emit('update:modelValue', $event)"
  >
    <NRadioButton
      v-for="option in options"
      :key="option.value"
      :value="option.value"
      :disabled="option.disabled"
    >
      {{ option.label }}
    </NRadioButton>
  </NRadioGroup>
</template>
