<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AppInput, AppSelect } from '@/shared/ui'
import type { MeasureTemplate } from '../api/category-lookup'
import { formatMeasure, parseMeasure, type MeasurePart } from '../model/measure'

const props = defineProps<{ modelValue: string; templates: MeasureTemplate[]; disabled: boolean; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const templateIndex = ref(0)
const parts = ref<MeasurePart[]>([])
const unparsed = ref('')
const template = computed(() => props.templates[templateIndex.value])
let emitted: string | null = null

function reset(value: string) {
  let index = props.templates.findIndex((candidate) => !!value && parseMeasure(candidate, value) !== null)
  if (index < 0) index = 0
  templateIndex.value = index
  const current = props.templates[index]
  if (!current) { parts.value = []; unparsed.value = value; return }
  const parsed = value ? parseMeasure(current, value) : null
  unparsed.value = value && !parsed ? value : ''
  parts.value = parsed ?? current.modules.map((module) => ({ value: '', unit: module.units[0]?.label ?? '' }))
}
watch(() => [props.modelValue, props.templates] as const, ([value]) => {
  if (emitted === value) { emitted = null; return }
  reset(value)
}, { immediate: true })

function changed() {
  if (!template.value) return
  unparsed.value = ''
  emitted = formatMeasure(template.value, parts.value)
  emit('update:modelValue', emitted)
}
function changeTemplate(value: string | number | null) {
  const index = props.templates.findIndex((item) => item.id === String(value))
  if (index < 0) return
  templateIndex.value = index
  parts.value = props.templates[index].modules.map((module) => ({ value: '', unit: module.units[0]?.label ?? '' }))
  changed()
}
</script>

<template>
  <div v-if="template" class="product-measure">
    <AppInput v-if="unparsed" :model-value="unparsed" readonly :aria-label="label" />
    <AppSelect v-if="templates.length > 1" :model-value="template.id"
      :options="templates.map((item) => ({ label: item.name, value: item.id }))"
      :disabled="disabled" @update:model-value="changeTemplate" />
    <div class="product-measure__parts">
      <template v-for="(module, index) in template.modules" :key="`${module.id}-${index}`">
        <span v-if="module.prefix">{{ module.prefix }}</span>
        <AppInput v-model="parts[index].value" :aria-label="`${label} ${index + 1}`" inputmode="decimal"
          :placeholder="module.placeholder" :readonly="disabled" @update:model-value="changed" />
        <AppSelect v-if="module.units.length" v-model="parts[index].unit" :options="module.units.map((unit) => ({ label: unit.label, value: unit.label }))"
          :aria-label="`${label} ${index + 1} 单位`" :disabled="disabled" @update:model-value="changed" />
        <span v-if="module.suffix">{{ module.suffix }}</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.product-measure { display:flex; flex-direction:column; gap:var(--space-2); width:100%; }
.product-measure__parts { display:flex; align-items:center; flex-wrap:wrap; gap:var(--space-2); }
.product-measure__parts :deep(.app-field) { flex:1 1 76px; min-width:70px; }
</style>
