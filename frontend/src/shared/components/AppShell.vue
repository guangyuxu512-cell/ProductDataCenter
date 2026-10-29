<script setup lang="ts">
import { computed, h } from 'vue'
import type { Component } from 'vue'
import { NMenu } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'

import brandMarkUrl from '@/assets/brand/siyu-ai-mark.png'
import AppOverlayHost from '@/shared/ui/AppOverlayHost.vue'

export interface AppNavigationModuleItem {
  type: 'module'
  moduleCode: string
  moduleName: string
  routePath: string
  icon: Component
}

export interface AppNavigationGroupItem {
  type: 'group'
  groupCode: string
  groupName: string
  icon: Component
  children: AppNavigationModuleItem[]
}

export type AppNavigationItem = AppNavigationModuleItem | AppNavigationGroupItem

const props = withDefaults(
  defineProps<{
    appName?: string
    pageLabel?: string
    navigation: AppNavigationItem[]
  }>(),
  {
    appName: '思余AI中控台',
  },
)

const route = useRoute()
const router = useRouter()
const isDevelopment = import.meta.env.DEV
const primaryNavigation = computed(() =>
  props.navigation.filter(
    (item) => item.type === 'group' || item.moduleCode !== 'settings',
  ),
)
const settingsNavigation = computed(() =>
  props.navigation.filter(
    (item): item is AppNavigationModuleItem =>
      item.type === 'module' && item.moduleCode === 'settings',
  ),
)
const navigationModules = computed(() =>
  props.navigation.flatMap((item) =>
    item.type === 'group' ? item.children : [item],
  ),
)
const navigationGroupKeys = computed(() =>
  props.navigation
    .filter((item): item is AppNavigationGroupItem => item.type === 'group')
    .map((item) => item.groupCode),
)

const activeNavigationKey = computed(() => {
  const routeModuleCode = route.meta.moduleCode
  if (
    typeof routeModuleCode === 'string' &&
    navigationModules.value.some((item) => item.moduleCode === routeModuleCode)
  ) {
    return routeModuleCode
  }

  return (
    navigationModules.value.find((item) => item.routePath === route.path)
      ?.moduleCode ?? null
  )
})

const activeNavigationLabel = computed(
  () =>
    props.pageLabel ??
    navigationModules.value.find(
      (item) => item.moduleCode === activeNavigationKey.value,
    )?.moduleName ??
    '工作台',
)

function renderPrimaryNavigationLabel(label: string, active = false) {
  return () =>
    h(
      'span',
      {
        class: [
          'app-shell__nav-label',
          { 'app-shell__nav-label--active': active },
        ],
      },
      label,
    )
}

function createMenuOptions(navigation: AppNavigationItem[]): MenuOption[] {
  return navigation.map((item) => {
    if (item.type === 'group') {
      return {
        key: item.groupCode,
        icon: () => h(item.icon, { size: 17, strokeWidth: 1.8 }),
        label: renderPrimaryNavigationLabel(item.groupName),
        children: item.children.map((child) => ({
          key: child.moduleCode,
          icon: () => h(child.icon, { size: 17, strokeWidth: 1.8 }),
          label: child.moduleName,
        })),
      }
    }
    return {
      key: item.moduleCode,
      icon: () => h(item.icon, { size: 17, strokeWidth: 1.8 }),
      label: renderPrimaryNavigationLabel(
        item.moduleName,
        item.moduleCode === activeNavigationKey.value,
      ),
    }
  })
}

const menuOptions = computed<MenuOption[]>(() =>
  createMenuOptions(primaryNavigation.value),
)
const settingsMenuOptions = computed<MenuOption[]>(() =>
  createMenuOptions(settingsNavigation.value),
)

function navigate(key: string): void {
  const target = navigationModules.value.find((item) => item.moduleCode === key)
  if (target && target.routePath !== route.path) {
    void router.push(target.routePath)
  }
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-shell__sidebar">
      <div class="app-shell__brand">
        <img
          class="app-shell__brand-mark"
          :src="brandMarkUrl"
          alt=""
          aria-hidden="true"
        />
        <strong>{{ appName }}</strong>
      </div>
      <nav class="app-shell__navigation" aria-label="主导航">
        <NMenu
          :value="activeNavigationKey"
          :options="menuOptions"
          :indent="12"
          :default-expanded-keys="navigationGroupKeys"
          @update:value="navigate"
        />
      </nav>
      <div v-if="isDevelopment" class="app-shell__sidebar-footer">
        <span />
        开发预览
      </div>
      <nav
        v-if="settingsMenuOptions.length"
        class="app-shell__settings-navigation"
        aria-label="系统设置主导航"
      >
        <NMenu
          :value="activeNavigationKey"
          :options="settingsMenuOptions"
          :indent="12"
          @update:value="navigate"
        />
      </nav>
    </aside>

    <section class="app-shell__workspace">
      <header class="app-shell__topbar">
        <div class="app-shell__topbar-leading">
          <slot name="topbar-leading">
            <div class="app-shell__breadcrumb" aria-label="当前位置">
              <span>中控台</span>
              <span aria-hidden="true">/</span>
              <strong>{{ activeNavigationLabel }}</strong>
            </div>
          </slot>
        </div>
        <div class="app-shell__topbar-actions">
          <slot name="topbar-actions" />
        </div>
      </header>
      <AppOverlayHost />
      <main class="app-shell__content">
        <slot />
      </main>
    </section>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  width: 100%;
  height: 100%;
  min-height: 0;
  grid-template-columns: var(--layout-sidebar-width) minmax(0, 1fr);
  overflow: hidden;
  background: var(--bg-app);
}

.app-shell__sidebar {
  isolation: isolate;
  display: flex;
  min-height: 0;
  flex-direction: column;
  border-right: 1px solid var(--sidebar-border);
  color: var(--sidebar-text);
  background: var(--bg-sidebar);
}

.app-shell__brand {
  display: flex;
  height: var(--layout-topbar-height);
  flex: 0 0 var(--layout-topbar-height);
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--sidebar-border);
  -webkit-app-region: drag;
  app-region: drag;
}

.app-shell__brand-mark {
  display: block;
  width: calc(var(--control-height-compact) + var(--space-2));
  height: var(--control-height-compact);
  flex: 0 0 calc(var(--control-height-compact) + var(--space-2));
  object-fit: contain;
}

.app-shell__brand strong {
  display: block;
  color: var(--sidebar-text-active);
  font-size: var(--font-size-body);
  line-height: var(--line-height-compact);
}

.app-shell__navigation {
  min-height: 0;
  flex: 1;
  padding: var(--space-3) var(--space-2);
  overflow-y: auto;
}

:deep(.app-shell__nav-label) {
  box-sizing: border-box;
  display: block;
  width: 100%;
  padding-left: var(--space-2);
  border-left: 2px solid transparent;
  line-height: var(--line-height-body);
  text-align: left;
}

:deep(.app-shell__nav-label--active) {
  border-left-color: var(--color-accent);
  font-weight: var(--font-weight-medium);
}

.app-shell__sidebar-footer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  color: var(--sidebar-text);
  font-size: var(--font-size-secondary);
}

.app-shell__settings-navigation {
  flex: 0 0 auto;
  padding: var(--space-2);
  border-top: 1px solid var(--sidebar-border);
}

.app-shell__sidebar-footer span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sidebar-text);
}

.app-shell__workspace {
  position: relative;
  display: grid;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-rows: var(--layout-topbar-height) minmax(0, 1fr);
}

.app-shell__topbar {
  isolation: isolate;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0
    calc(
      var(--layout-page-padding-x) +
        max(
          0px,
          calc(
            100vw - env(titlebar-area-x, 0px) - env(titlebar-area-width, 100vw)
          )
        )
    )
    0 var(--layout-page-padding-x);
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-topbar);
  -webkit-app-region: drag;
  app-region: drag;
}

.app-shell__topbar-leading,
.app-shell__topbar-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.app-shell__topbar-actions {
  -webkit-app-region: no-drag;
  app-region: no-drag;
}

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

.app-shell__content {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  background: var(--bg-app);
}
</style>
