<script setup lang="ts">
import { computed } from 'vue'
import { Package } from '@lucide/vue'
import {
  NConfigProvider, NDialogProvider, NGlobalStyle, NLoadingBarProvider,
  NMessageProvider, NNotificationProvider, darkTheme, dateZhCN, zhCN,
} from 'naive-ui'
import { RouterView } from 'vue-router'
import { createNaiveThemeOverrides } from '@/app/providers/naive-theme'
import AppShell from '@/shared/components/AppShell.vue'
import type { AppNavigationItem } from '@/shared/components/AppShell.vue'
import ThemeSelector from '@/shared/components/ThemeSelector.vue'
import { APP_OVERLAY_HOST_SELECTOR } from '@/shared/ui/overlay-host'
import { useThemeStore } from '@/stores/theme'

const theme = useThemeStore()
const naiveTheme = computed(() => theme.resolvedTheme === 'dark' ? darkTheme : null)
const overrides = computed(() => createNaiveThemeOverrides(theme.resolvedPreset))
const navigation: AppNavigationItem[] = [
  { type: 'module', moduleCode: 'product-library', moduleName: '商品库', routePath: '/products', icon: Package },
]
</script>

<template>
  <NConfigProvider abstract :theme="naiveTheme" :theme-overrides="overrides" :locale="zhCN" :date-locale="dateZhCN">
    <NGlobalStyle />
    <NLoadingBarProvider>
      <NDialogProvider :to="APP_OVERLAY_HOST_SELECTOR">
        <NNotificationProvider>
          <NMessageProvider>
            <AppShell app-name="商品云库" :navigation="navigation">
              <template #topbar-leading>
                <div class="app-shell__breadcrumb" aria-label="当前位置">
                  <span>商品云库</span><span aria-hidden="true">/</span><strong>商品库</strong>
                </div>
              </template>
              <template #topbar-actions><ThemeSelector /></template>
              <RouterView />
            </AppShell>
          </NMessageProvider>
        </NNotificationProvider>
      </NDialogProvider>
    </NLoadingBarProvider>
  </NConfigProvider>
</template>

<style scoped>
.app-shell__breadcrumb {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-tertiary);
  font-size: var(--font-size-secondary);
}
.app-shell__breadcrumb strong {
  color: var(--text-secondary);
  font-weight: var(--font-weight-medium);
}
</style>
