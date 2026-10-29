/// <reference types="vite/client" />

interface Window {
  desktop?: { appearance: { setTitleBarTheme(theme: 'light' | 'dark'): void } }
}
