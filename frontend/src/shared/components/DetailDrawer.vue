<script setup lang="ts">
import AppDrawer from '@/shared/ui/AppDrawer.vue'
import type { OverlaySize } from '@/shared/ui/types'

withDefaults(
  defineProps<{
    show: boolean
    title?: string
    size?: OverlaySize
    bodyContentClass?: string
  }>(),
  { title: '', size: 'md', bodyContentClass: '' },
)

defineEmits<{ 'update:show': [value: boolean] }>()
</script>

<template>
  <AppDrawer
    :show="show"
    :title="title"
    :size="size"
    :body-content-class="bodyContentClass"
    @update:show="$emit('update:show', $event)"
  >
    <template v-if="$slots.header" #header><slot name="header" /></template>
    <slot />
    <template v-if="$slots.footer" #footer><slot name="footer" /></template>
  </AppDrawer>
</template>
