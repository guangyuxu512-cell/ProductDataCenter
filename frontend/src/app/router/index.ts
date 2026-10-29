import { createRouter, createWebHashHistory } from 'vue-router'
import ProductLibraryPage from '@/pages/product-library/ProductLibraryPage.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/products' },
    { path: '/products', name: 'products', component: ProductLibraryPage, meta: { moduleCode: 'product-library' } },
    { path: '/:pathMatch(.*)*', redirect: '/products' },
  ],
})
