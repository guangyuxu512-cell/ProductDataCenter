<script setup lang="ts">
import { NDrawer, NDrawerContent } from 'naive-ui'

import { APP_OVERLAY_HOST_SELECTOR } from './overlay-host'
import type { OverlaySize } from './types'

const drawerWidths: Record<OverlaySize, string> = {
  sm: 'var(--drawer-width-sm)',
  md: 'var(--drawer-width-md)',
  lg: 'var(--drawer-width-lg)',
}

withDefaults(
  defineProps<{
    show: boolean
    title?: string
    size?: OverlaySize
    closable?: boolean
    to?: string | HTMLElement
    bodyContentClass?: string
  }>(),
  {
    title: '',
    size: 'md',
    closable: true,
    to: APP_OVERLAY_HOST_SELECTOR,
    bodyContentClass: '',
  },
)

defineEmits<{
  'update:show': [value: boolean]
}>()
</script>

<template>
  <NDrawer
    :show="show"
    :width="drawerWidths[size]"
    :mask-closable="false"
    :to="to"
    @update:show="$emit('update:show', $event)"
  >
    <NDrawerContent
      :title="title"
      :closable="closable"
      :body-content-class="bodyContentClass"
    >
      <template v-if="$slots.header" #header>
        <slot name="header" />
      </template>
      <slot />
      <template v-if="$slots.footer" #footer>
        <slot name="footer" />
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
