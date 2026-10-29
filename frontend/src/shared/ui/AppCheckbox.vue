<script setup lang="ts">
import { NCheckbox } from 'naive-ui'

withDefaults(
  defineProps<{
    modelValue?: boolean
    indeterminate?: boolean
    disabled?: boolean
  }>(),
  {
    modelValue: false,
    indeterminate: false,
    disabled: false,
  },
)

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <NCheckbox
    :checked="modelValue"
    :indeterminate="indeterminate"
    :disabled="disabled"
    @update:checked="$emit('update:modelValue', $event)"
  >
    <slot />
  </NCheckbox>
</template>
