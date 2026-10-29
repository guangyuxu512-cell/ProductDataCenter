<script setup lang="ts">
import { NButton } from 'naive-ui'

export type AppButtonTone = 'primary' | 'secondary' | 'danger' | 'text' | 'link'

// Explicit opt-in for themed links; existing neutral text actions stay unchanged.
const linkTheme = {
  textColorTextPrimary: 'var(--text-link)',
  textColorTextHoverPrimary: 'var(--text-link)',
  textColorTextPressedPrimary: 'var(--text-link)',
  textColorTextFocusPrimary: 'var(--text-link)',
  textColorTextDisabledPrimary: 'var(--text-disabled)',
}

withDefaults(
  defineProps<{
    tone?: AppButtonTone
    size?: 'small' | 'medium'
    loading?: boolean
    disabled?: boolean
    block?: boolean
    attrType?: 'button' | 'submit' | 'reset'
  }>(),
  {
    tone: 'secondary',
    size: 'medium',
    loading: false,
    disabled: false,
    block: false,
    attrType: 'button',
  },
)

defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <NButton
    :size="size"
    :type="
      tone === 'primary' || tone === 'link'
        ? 'primary'
        : tone === 'danger'
          ? 'error'
          : 'default'
    "
    :text="tone === 'link'"
    :theme-overrides="tone === 'link' ? linkTheme : undefined"
    :quaternary="tone === 'text'"
    :loading="loading"
    :disabled="disabled"
    :block="block"
    :attr-type="attrType"
    @click="$emit('click', $event)"
  >
    <slot />
  </NButton>
</template>
