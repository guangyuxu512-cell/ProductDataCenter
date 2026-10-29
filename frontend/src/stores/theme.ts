import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type ThemePreset = 'graphite' | 'forest' | 'coral' | 'midnight'
export type ThemeMode = ThemePreset | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'control-center.theme-mode'

function normalizeThemeMode(value: string | null): ThemeMode {
  if (value === 'dark') return 'midnight'
  if (value === 'light') return 'graphite'
  return value === 'graphite' ||
    value === 'forest' ||
    value === 'coral' ||
    value === 'midnight' ||
    value === 'system'
    ? value
    : 'graphite'
}

function readStoredThemeMode(): ThemeMode {
  if (typeof window === 'undefined') return 'graphite'
  try {
    return normalizeThemeMode(window.localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return 'graphite'
  }
}

function persistThemeMode(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Theme persistence is optional when storage is unavailable.
  }
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readStoredThemeMode())
  const systemPrefersDark = ref(false)
  let initialized = false

  const resolvedPreset = computed<ThemePreset>(() =>
    mode.value === 'system'
      ? systemPrefersDark.value
        ? 'midnight'
        : 'graphite'
      : mode.value,
  )
  const resolvedTheme = computed<ResolvedTheme>(() =>
    resolvedPreset.value === 'midnight' ? 'dark' : 'light',
  )

  function applyPreset(preset: ThemePreset): void {
    document.documentElement.dataset.theme = resolvedTheme.value
    document.documentElement.dataset.themePreset = preset
    document.documentElement.style.colorScheme = resolvedTheme.value
  }

  function setMode(value: ThemeMode | ResolvedTheme): void {
    mode.value = normalizeThemeMode(value)
  }

  function initialize(): void {
    if (initialized) return
    initialized = true

    const mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)')
    systemPrefersDark.value = mediaQuery?.matches ?? false
    mediaQuery?.addEventListener('change', (event) => {
      systemPrefersDark.value = event.matches
    })

    watch(mode, persistThemeMode, { flush: 'sync' })
    watch(resolvedPreset, applyPreset, { immediate: true, flush: 'sync' })
    watch(
      resolvedTheme,
      (theme) => {
        window.desktop?.appearance.setTitleBarTheme(theme)
      },
      { immediate: true, flush: 'sync' },
    )
  }

  return { mode, resolvedPreset, resolvedTheme, initialize, setMode }
})
