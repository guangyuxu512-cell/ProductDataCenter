<script setup lang="ts">
import { NSelect, NTooltip } from 'naive-ui'
import type { SelectFilter, SelectOption, SelectProps } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import type { ComponentPublicInstance } from 'vue'

import { APP_OVERLAY_HOST_SELECTOR } from './overlay-host'
import type { AppOptionValue, AppSelectValue, FieldWidth } from './types'

const props = withDefaults(
  defineProps<{
    modelValue?: AppSelectValue | null
    options: SelectOption[]
    placeholder?: string
    width?: FieldWidth
    clearable?: boolean
    filterable?: boolean
    loading?: boolean
    disabled?: boolean
    multiple?: boolean
    maxTagCount?: number | 'responsive'
    renderLabel?: SelectProps['renderLabel']
    labelTooltip?: boolean
    filter?: SelectFilter
    menuProps?: SelectProps['menuProps']
    placement?: SelectProps['placement']
    to?: SelectProps['to']
    viewportSafeMenu?: boolean
  }>(),
  {
    modelValue: null,
    placeholder: '',
    width: 'full',
    clearable: false,
    filterable: false,
    loading: false,
    disabled: false,
    multiple: false,
    maxTagCount: undefined,
    renderLabel: undefined,
    labelTooltip: false,
    filter: undefined,
    menuProps: undefined,
    placement: 'bottom-start',
    to: undefined,
    viewportSafeMenu: true,
  },
)

const mergedMenuProps = computed<SelectProps['menuProps']>(() => ({
  ...props.menuProps,
  class: [
    props.viewportSafeMenu ? 'app-select-menu--viewport-safe' : null,
    props.menuProps?.class,
  ],
}))

// NSelect otherwise inherits the closest modal/drawer body as its teleport
// target. Those bodies intentionally clip and scroll their own content, which
// can cut off a menu. Prefer the application overlay layer after mount and
// fall back to Naive's fullscreen/body target for layouts (such as login) that
// do not render AppOverlayHost. Explicit consumer targets always win.
const defaultOverlayTarget = ref<SelectProps['to']>(true)
onMounted(() => {
  defaultOverlayTarget.value = document.querySelector(APP_OVERLAY_HOST_SELECTOR)
    ? APP_OVERLAY_HOST_SELECTOR
    : true
})
const resolvedTo = computed<SelectProps['to']>(() =>
  props.to === undefined ? defaultOverlayTarget.value : props.to,
)

// Naive uses renderLabel for both selected text and options. Its searchable
// selected overlay has pointer-events:none; restore events only on this label
// so the existing Tooltip can observe hover. Click/keyboard handling still
// belongs to NSelect. Custom renderTag retains Naive's native precedence.
const mergedRenderLabel = computed<SelectProps['renderLabel']>(() => {
  if (!props.labelTooltip) return props.renderLabel
  return (option, selected) => {
    // Naive's public callback uses an intersection of option variants. Read
    // the common label through the existing SelectOption contract instead.
    const label = (option as SelectOption).label
    const content = props.renderLabel
      ? props.renderLabel(option, selected)
      : typeof label === 'function'
        ? label(option, selected)
        : label
    if (typeof label !== 'string') return content
    let trigger: HTMLElement | null = null
    return h(
      NTooltip,
      {
        to: resolvedTo.value,
        getDisabled: () =>
          !trigger || trigger.scrollWidth <= trigger.clientWidth,
        contentStyle: {
          maxWidth: 'calc(100vw - 2 * var(--overlay-viewport-safe-gap))',
          whiteSpace: 'normal',
          overflowWrap: 'anywhere',
        },
      },
      {
        trigger: () =>
          h(
            'span',
            {
              class: 'app-select-label',
              ref: (element: Element | ComponentPublicInstance | null) => {
                trigger = element instanceof HTMLElement ? element : null
              },
              style: {
                display: 'inline-block',
                width: '100%',
                maxWidth: '100%',
                minWidth: '0',
                verticalAlign: 'bottom',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                pointerEvents: 'auto',
              },
            },
            [content],
          ),
        default: () => label,
      },
    )
  }
})

const emit = defineEmits<{
  'update:modelValue': [value: AppOptionValue | null]
  'update:values': [value: AppOptionValue[]]
}>()

function updateValue(value: AppSelectValue | null): void {
  if (props.multiple) {
    emit('update:values', Array.isArray(value) ? value : [])
    return
  }
  if (!Array.isArray(value)) emit('update:modelValue', value)
}
</script>

<template>
  <NSelect
    class="app-field"
    :class="`app-field--${width}`"
    size="medium"
    :value="modelValue"
    :options="options"
    :placeholder="placeholder"
    :clearable="clearable"
    :filterable="filterable"
    :loading="loading"
    :disabled="disabled"
    :multiple="multiple"
    :max-tag-count="maxTagCount"
    :render-label="mergedRenderLabel"
    :filter="filter"
    :menu-props="mergedMenuProps"
    :placement="placement"
    :to="resolvedTo"
    @update:value="updateValue"
  />
</template>

<style>
.app-select-menu--viewport-safe {
  --n-height: var(--select-menu-max-height) !important;
  pointer-events: auto;
}
</style>
