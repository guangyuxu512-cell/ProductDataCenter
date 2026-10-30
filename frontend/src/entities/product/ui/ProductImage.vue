<script setup lang="ts">
import { NConfigProvider, NImage, NText } from 'naive-ui'
import { computed, ref, watch } from 'vue'
import { AppButton, createListDensityTheme } from '@/shared/ui'
import type { ListDensity } from '@/shared/ui'
import { thumbnailImageUrl } from '../model/thumbnail-image-url'

// Shared source: b364a89a9955ffe4aae1c3fb6dbfcabfd0dedf8f.
const props = withDefaults(
  defineProps<{
    src: string | null
    title: string
    size?: 'thumbnail' | 'summary'
    density?: ListDensity
  }>(),
  { size: 'summary', density: 'default' },
)
const failed = ref(false),
  revision = ref(0),
  useOriginal = ref(false)
const displaySrc = computed(() => {
  if (!props.src || useOriginal.value || props.size !== 'thumbnail') return props.src
  return thumbnailImageUrl(props.src)
})
// A null root respects the clipping of the table's internal scroll container.
// When observers are unavailable, Naive UI falls back to native lazy loading.
const observerOptions = typeof IntersectionObserver === 'undefined'
  ? undefined
  : { rootMargin: '120px' }
watch(
  () => props.src,
  () => {
    failed.value = false
    useOriginal.value = false
  },
  { flush: 'sync' },
)
function retry() {
  failed.value = false
  useOriginal.value = false
  revision.value += 1
}
function onImageError(event: Event) {
  const image = event.currentTarget
  // An old request may fail just as the row changes to a different product.
  if (!(image instanceof HTMLImageElement) || image.getAttribute('src') !== displaySrc.value) return
  if (!useOriginal.value && props.src && displaySrc.value !== props.src) {
    useOriginal.value = true
  } else {
    failed.value = true
  }
}
</script>

<template>
  <div
    class="product-image"
    :class="[
      'product-image--' + size,
      {
        'product-image--compact': size === 'thumbnail' && density === 'compact',
      },
    ]"
  >
    <NConfigProvider
      abstract
      :theme-overrides="
        createListDensityTheme(size === 'thumbnail' ? density : 'default')
      "
    >
      <NText v-if="!src" :depth="3">—</NText>
      <AppButton
        v-else-if="failed"
        tone="text"
        aria-label="重试商品图片"
        @click="retry"
        >重试</AppButton
      >
      <NImage
        v-else
        :key="`${displaySrc}:${revision}`"
        :src="displaySrc ?? undefined"
        :preview-src="src ?? undefined"
        :alt="title"
        object-fit="contain"
        lazy
        :intersection-observer-options="observerOptions"
        :img-props="{ referrerpolicy: 'no-referrer' }"
        @error="onImageError"
      />
    </NConfigProvider>
  </div>
</template>

<style scoped>
.product-image {
  --product-image-size: 80px;
  display: flex;
  justify-content: center;
  align-items: center;
  height: var(--product-image-size);
}
.product-image--thumbnail {
  --product-image-size: 64px;
}
.product-image--compact {
  --product-image-size: var(--list-compact-image-size);
  width: var(--product-image-size);
  flex: 0 0 var(--product-image-size);
}
.product-image :deep(img) {
  width: var(--product-image-size);
  height: var(--product-image-size);
  object-fit: contain;
}
</style>
