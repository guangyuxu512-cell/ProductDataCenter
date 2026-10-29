<script setup lang="ts">
import { NSwitch } from 'naive-ui'

withDefaults(
  defineProps<{
    modelValue?: boolean
    disabled?: boolean
    loading?: boolean
  }>(),
  {
    modelValue: false,
    disabled: false,
    loading: false,
  },
)

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <NSwitch
    size="medium"
    :value="modelValue"
    :disabled="disabled"
    :aria-disabled="disabled"
    :loading="loading"
    @update:value="$emit('update:modelValue', $event)"
  />
</template>
