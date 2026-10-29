<script setup lang="ts">
import { computed } from 'vue'
import { NDropdown } from 'naive-ui'
import type { DropdownOption } from 'naive-ui'

import { useThemeStore, type ThemeMode } from '@/stores/theme'
import AppButton from '@/shared/ui/AppButton.vue'

const themeStore = useThemeStore()

const options: DropdownOption[] = [
  { key: 'graphite', label: '石墨浅色' },
  { key: 'forest', label: '森林绿' },
  { key: 'coral', label: '珊瑚红' },
  { key: 'midnight', label: '午夜青' },
  { key: 'system', label: '跟随系统' },
]

const currentLabel = computed(
  () => options.find((option) => option.key === themeStore.mode)?.label,
)

function selectTheme(key: string | number): void {
  themeStore.setMode(key as ThemeMode)
}
</script>

<template>
  <NDropdown trigger="click" :options="options" @select="selectTheme">
    <AppButton
      tone="text"
      class="theme-selector"
      aria-label="切换主题"
      :title="`当前主题：${currentLabel}`"
    >
      <span class="theme-selector__content">
        <span class="theme-selector__mark" aria-hidden="true" />
        <span>主题</span>
        <span class="theme-selector__current">{{ currentLabel }}</span>
      </span>
    </AppButton>
  </NDropdown>
</template>

<style scoped>
.theme-selector__content {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  white-space: nowrap;
}

.theme-selector__mark {
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: linear-gradient(
    90deg,
    var(--text-primary) 0 50%,
    var(--bg-surface-solid) 50% 100%
  );
}

.theme-selector__current {
  color: var(--text-tertiary);
  font-size: var(--font-size-secondary);
}
</style>
