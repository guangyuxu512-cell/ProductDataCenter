import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'
import router from './app/router'
import { queryClient } from './app/providers/query-client'
import { useThemeStore } from './stores/theme'
import './shared/styles/theme.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(VueQueryPlugin, { queryClient })
useThemeStore(pinia).initialize()
app.mount('#app')
