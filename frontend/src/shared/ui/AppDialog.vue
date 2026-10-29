<script setup lang="ts">
import { NModal, NTooltip } from 'naive-ui'

import AppButton from './AppButton.vue'
import { APP_OVERLAY_HOST_SELECTOR } from './overlay-host'
import type { DialogSize } from './types'

const dialogWidths: Record<DialogSize, string> = {
  sm: 'var(--dialog-width-sm)',
  md: 'var(--dialog-width-md)',
  lg: 'var(--dialog-width-lg)',
  xl: 'var(--dialog-width-xl)',
  workspace: 'var(--dialog-width-workspace)',
}

function dialogStyle(size: DialogSize) {
  if (size === 'workspace')
    return {
      width: dialogWidths[size],
      maxWidth: 'var(--dialog-width-workspace)',
      height: 'var(--dialog-height-workspace)',
      maxHeight: 'var(--dialog-height-workspace)',
    }
  return {
    width: dialogWidths[size],
    maxWidth: 'calc(100vw - var(--space-8))',
    maxHeight: 'var(--dialog-max-height)',
  }
}

withDefaults(
  defineProps<{
    show: boolean
    title: string
    size?: DialogSize
    positiveText?: string
    negativeText?: string
    showNegative?: boolean
    loading?: boolean
    positiveDisabled?: boolean
    positiveDisabledReason?: string | null
    contentScrollable?: boolean
    to?: string | HTMLElement
  }>(),
  {
    size: 'md',
    positiveText: '确认',
    negativeText: '取消',
    showNegative: true,
    loading: false,
    positiveDisabled: false,
    positiveDisabledReason: null,
    contentScrollable: true,
    to: APP_OVERLAY_HOST_SELECTOR,
  },
)

const emit = defineEmits<{
  'update:show': [value: boolean]
  confirm: []
  cancel: []
}>()

function cancel(): void {
  emit('update:show', false)
  emit('cancel')
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :class="['app-dialog', { 'app-dialog--workspace': size === 'workspace' }]"
    :content-scrollable="contentScrollable"
    :style="dialogStyle(size)"
    :bordered="true"
    :mask-closable="false"
    :to="to"
    @update:show="$emit('update:show', $event)"
  >
    <template #header>
      <div class="app-dialog__heading">
        <div class="app-dialog__title">{{ title }}</div>
        <div v-if="$slots.description" class="app-dialog__description">
          <slot name="description" />
        </div>
      </div>
    </template>
    <slot />
    <template #footer>
      <div class="app-dialog__footer">
        <div v-if="$slots['footer-start']" class="app-dialog__footer-start">
          <slot name="footer-start" />
        </div>
        <div class="app-dialog__footer-actions">
          <AppButton v-if="showNegative" @click="cancel">{{
            negativeText
          }}</AppButton>
          <NTooltip
            v-if="positiveDisabled && positiveDisabledReason"
            placement="top"
          >
            <template #trigger>
              <span class="app-dialog__disabled-action">
                <AppButton
                  tone="primary"
                  :loading="loading"
                  disabled
                  @click="$emit('confirm')"
                >
                  {{ positiveText }}
                </AppButton>
              </span>
            </template>
            {{ positiveDisabledReason }}
          </NTooltip>
          <AppButton
            v-else
            tone="primary"
            :loading="loading"
            :disabled="positiveDisabled"
            @click="$emit('confirm')"
          >
            {{ positiveText }}
          </AppButton>
        </div>
      </div>
    </template>
  </NModal>
</template>

<style>
.app-dialog {
  overflow: hidden;
}

.app-dialog > .n-card-header,
.app-dialog > .n-card__footer {
  flex: 0 0 auto;
}

.app-dialog > .n-card__content-scrollbar,
.app-dialog > .n-card-content {
  flex: 1 1 auto;
  min-height: 0;
}

.app-dialog--workspace > .n-card-content {
  overflow: hidden;
}

.app-dialog__heading {
  min-width: 0;
}

.app-dialog__title {
  color: var(--text-primary);
  font-weight: var(--font-weight-semibold);
}

.app-dialog__description {
  margin-top: var(--space-1);
  color: var(--text-secondary);
  font-size: var(--font-size-secondary);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
}

.app-dialog__description > :first-child {
  margin-top: 0;
}

.app-dialog__description > :last-child {
  margin-bottom: 0;
}

.app-dialog__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
}

.app-dialog__footer-start {
  min-width: 0;
  margin-right: auto;
}

.app-dialog__footer-actions {
  display: flex;
  flex: 0 0 auto;
  gap: var(--space-3);
}

.app-dialog__disabled-action {
  display: inline-flex;
}
</style>
