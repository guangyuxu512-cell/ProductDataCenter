<script setup lang="ts">
import AppDialog from '@/shared/ui/AppDialog.vue'
import type { OverlaySize } from '@/shared/ui/types'

withDefaults(
  defineProps<{
    show: boolean
    title: string
    size?: OverlaySize
    submitting?: boolean
    submitText?: string
    submitDisabled?: boolean
    submitDisabledReason?: string | null
  }>(),
  {
    size: 'md',
    submitting: false,
    submitText: '保存',
    submitDisabled: false,
    submitDisabledReason: null,
  },
)

defineEmits<{
  'update:show': [value: boolean]
  submit: []
  cancel: []
}>()
</script>

<template>
  <AppDialog
    :show="show"
    :title="title"
    :size="size"
    :loading="submitting"
    :positive-disabled="submitDisabled"
    :positive-disabled-reason="submitDisabledReason"
    :positive-text="submitText"
    @update:show="$emit('update:show', $event)"
    @confirm="$emit('submit')"
    @cancel="$emit('cancel')"
  >
    <template v-if="$slots.description" #description>
      <slot name="description" />
    </template>
    <slot />
    <template v-if="$slots['footer-start']" #footer-start>
      <slot name="footer-start" />
    </template>
  </AppDialog>
</template>
