<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ProductImage } from '@/entities/product'

defineProps<{ src: string | null; title: string }>()
const target = ref<HTMLElement | null>(null)
const visible = ref(false)
let observer: IntersectionObserver | undefined
onMounted(() => {
  if (!target.value || typeof IntersectionObserver === 'undefined') {
    visible.value = true
    return
  }
  observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) {
      visible.value = true
      observer?.disconnect()
    }
  }, { rootMargin: '120px' })
  observer.observe(target.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <span ref="target" class="deferred-preview-thumbnail">
    <ProductImage v-if="visible" :src="src" :title="title" size="thumbnail" />
  </span>
</template>

<style scoped>
.deferred-preview-thumbnail {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
