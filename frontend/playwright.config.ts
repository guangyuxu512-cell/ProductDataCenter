import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4180',
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN', timezoneId: 'Asia/Shanghai',
    screenshot: 'only-on-failure', trace: 'retain-on-failure',
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--disable-dev-shm-usage'] },
  },
  webServer: {
    command: 'pnpm preview', url: 'http://127.0.0.1:4180', reuseExistingServer: !process.env.CI,
  },
})
