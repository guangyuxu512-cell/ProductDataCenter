<script setup lang="ts">
import { Copy } from '@lucide/vue'
import { NConfigProvider, NTooltip, useMessage } from 'naive-ui'
import { computed, ref } from 'vue'
import type { CSSProperties } from 'vue'
import { AppButton, createListDensityTheme } from '@/shared/ui'
import type { ListDensity } from '@/shared/ui'
import ProductImage from './ProductImage.vue'

// Shared source: b364a89a9955ffe4aae1c3fb6dbfcabfd0dedf8f. Use NTooltip
// instead of the installed NEllipsis's failing default click handler.
const props = withDefaults(
  defineProps<{
    productId: string | null
    title: string
    imageUrl: string | null
    density?: ListDensity
  }>(),
  { density: 'default' },
)
const message = useMessage(),
  copying = ref(false),
  titleElement = ref<HTMLElement | null>(null),
  idElement = ref<HTMLElement | null>(null)
const id = computed(() => (props.productId?.trim() ? props.productId : null))
const tooltipStyle: CSSProperties = {
  maxWidth:
    'min(var(--field-width-lg), calc(100vw - 2 * var(--overlay-viewport-safe-gap)))',
  whiteSpace: 'normal',
  overflowWrap: 'anywhere',
}
function clipped(element: HTMLElement | null) {
  return !!element && element.scrollWidth > element.clientWidth
}
async function copyId() {
  if (copying.value || !id.value) return
  copying.value = true
  try {
    await navigator.clipboard.writeText(id.value)
    message.success('商品ID已复制')
  } catch {
    message.error('复制失败，可选中商品ID手动复制')
  } finally {
    copying.value = false
  }
}
</script>

<template>
  <div
    class="product-info-cell"
    :class="{ 'product-info-cell--compact': density === 'compact' }"
  >
    <NConfigProvider
      abstract
      :theme-overrides="createListDensityTheme(density)"
    >
      <ProductImage
        :src="imageUrl"
        :title="title"
        size="thumbnail"
        :density="density"
      />
      <div class="product-info-cell__text">
        <NTooltip
          :get-disabled="() => !clipped(titleElement)"
          :content-style="tooltipStyle"
        >
          <template #trigger
            ><span ref="titleElement" class="product-info-cell__title">{{
              title
            }}</span></template
          >
          {{ title }}
        </NTooltip>
        <div class="product-info-cell__id">
          <NTooltip
            placement="top-start"
            :get-disabled="() => !id || !clipped(idElement)"
            :content-style="tooltipStyle"
          >
            <template #trigger
              ><span ref="idElement" class="product-info-cell__id-text"
                >ID：{{ id ?? '—' }}</span
              ></template
            >
            ID：{{ id }}
          </NTooltip>
          <NTooltip>
            <template #trigger
              ><AppButton
                class="product-info-cell__copy"
                size="small"
                tone="text"
                :loading="copying"
                :disabled="copying || !id"
                aria-label="复制商品ID"
                @click.stop="copyId"
                ><Copy :size="14" aria-hidden="true" /></AppButton
            ></template>
            复制商品ID
          </NTooltip>
        </div>
      </div>
    </NConfigProvider>
  </div>
</template>

<style scoped>
.product-info-cell {
  --product-id-copy-size: var(--control-height-compact);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  text-align: left;
}
.product-info-cell--compact {
  --product-id-copy-size: var(--list-compact-control-height);
  gap: var(--list-compact-gap);
  font-size: var(--list-compact-font-size);
}
.product-info-cell > :first-child {
  flex: 0 0 auto;
}
.product-info-cell__text {
  min-width: 0;
  flex: 1;
}
.product-info-cell__title,
.product-info-cell__id-text {
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.product-info-cell__title {
  color: var(--text-primary);
}
.product-info-cell__id {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--product-id-copy-size);
  width: 100%;
  max-width: calc(
    var(--field-width-sm) + var(--space-1) + var(--product-id-copy-size)
  );
  min-width: 0;
  align-items: center;
  gap: var(--space-1);
  color: var(--text-secondary);
  font-size: var(--font-size-secondary);
}
.product-info-cell--compact .product-info-cell__id {
  font-size: var(--list-compact-font-size);
}
.product-info-cell__id-text {
  min-width: 0;
  user-select: text;
}
.product-info-cell__copy {
  width: var(--product-id-copy-size);
  min-width: var(--product-id-copy-size);
}
</style>
