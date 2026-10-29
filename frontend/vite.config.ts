import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const token = env.BACKEND_API_TOKEN_FILE ? readFileSync(env.BACKEND_API_TOKEN_FILE, 'utf8').trim() : env.BACKEND_API_TOKEN
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      host: '127.0.0.1', port: 4180, strictPort: true,
      proxy: { '/api': { target: env.BACKEND_URL || 'http://127.0.0.1:8180',
        headers: token ? { Authorization: `Bearer ${token}` } : {} } },
    },
    preview: { host: '127.0.0.1', port: 4180, strictPort: true },
  }
})
