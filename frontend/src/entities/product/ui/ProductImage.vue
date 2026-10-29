<script setup lang="ts">
import { NConfigProvider, NImage, NText } from 'naive-ui'
import { ref, watch } from 'vue'
import { AppButton, createListDensityTheme } from '@/shared/ui'
import type { ListDensity } from '@/shared/ui'

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
  revision = ref(0)
watch(
  () => props.src,
  () => {
    failed.value = false
  },
)
function retry() {
  failed.value = false
  revision.value += 1
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
        :key="revision"
        :src="src"
        :alt="title"
        object-fit="contain"
        :img-props="{ loading: 'lazy', referrerpolicy: 'no-referrer' }"
        @error="failed = true"
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
