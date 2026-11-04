<script setup lang="ts">
import { NInput } from 'naive-ui'

import type { FieldWidth } from './types'

withDefaults(
  defineProps<{
    modelValue?: string | null
    placeholder?: string
    width?: FieldWidth
    type?: 'text' | 'password' | 'textarea'
    clearable?: boolean
    disabled?: boolean
    readonly?: boolean
    loading?: boolean
    maxlength?: number
    name?: string
    autocomplete?: 'username' | 'current-password' | 'off'
    autofocus?: boolean
    ariaLabel?: string
    inputmode?: 'text' | 'decimal' | 'numeric' | 'search' | 'email' | 'tel' | 'url'
  }>(),
  {
    modelValue: null,
    placeholder: '',
    width: 'full',
    type: 'text',
    clearable: false,
    disabled: false,
    readonly: false,
    loading: false,
    maxlength: undefined,
    name: undefined,
    autocomplete: undefined,
    autofocus: false,
    ariaLabel: undefined,
    inputmode: undefined,
  },
)

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <NInput
    class="app-field"
    :class="`app-field--${width}`"
    size="medium"
    :value="modelValue ?? ''"
    :type="type"
    :placeholder="placeholder"
    :clearable="clearable"
    :disabled="disabled"
    :readonly="readonly"
    :loading="loading"
    :maxlength="maxlength"
    :autofocus="autofocus"
    :input-props="{ name, autocomplete, inputmode, 'aria-label': ariaLabel }"
    @update:value="$emit('update:modelValue', $event)"
  />
</template>
