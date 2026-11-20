<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SelectOption, SelectProps } from 'naive-ui'
import { AppButton, AppInput, AppSelect } from '@/shared/ui'
import type { CategoryAttribute } from '../api/category-lookup'
import type { ProductAttributeValue } from '../model/contracts'
import { parseMultiMeasure } from '../model/measure'

type Rule = NonNullable<CategoryAttribute['multiMeasureRule']>
type Row = { key: number; material: string; amount: string; unit: string;
  original: ProductAttributeValue | null; raw: string; changed: boolean }

const props = defineProps<{ modelValue: ProductAttributeValue[]; options: CategoryAttribute['options'];
  rule: Rule; allowCustom: boolean; maxValues?: number | null; disabled: boolean; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: ProductAttributeValue[]] }>()
const rows = ref<Row[]>([])
let nextKey = 0
let lastValues = ''
let lastRule = ''
let emitted = ''

function blank(): Row {
  return { key: nextKey++, material: '', amount: '', unit: props.rule.units[0]?.label ?? '',
    original: null, raw: '', changed: false }
}
function reset(values: ProductAttributeValue[]) {
  rows.value = values.map((original) => {
    const parsed = parseMultiMeasure(props.rule, original.name, props.options)
    return parsed
      ? { ...blank(), material: parsed.name, amount: parsed.value, unit: parsed.unit, original: { ...original } }
      : { ...blank(), raw: original.name, original: { ...original } }
  })
  if (!rows.value.length) rows.value = [blank()]
}
watch(() => [props.modelValue, props.options, props.rule] as const, ([values, options, rule]) => {
  const valueSignature = JSON.stringify(values)
  const ruleSignature = JSON.stringify([options, rule])
  if (ruleSignature === lastRule && (valueSignature === emitted || valueSignature === lastValues)) {
    lastValues = valueSignature; emitted = ''; return
  }
  lastValues = valueSignature; lastRule = ruleSignature; emitted = ''
  reset(values)
}, { immediate: true, deep: true })

function changed() {
  const values = rows.value.flatMap((row) => {
    if (!row.changed && row.original) return [{ ...row.original }]
    if (!row.material.trim() && !row.amount.trim()) return []
    return [{ valueId: '0', name: `${row.material.trim()}${row.amount.trim()}${row.amount.trim() ? row.unit : ''}` }]
  })
  emitted = JSON.stringify(values)
  emit('update:modelValue', values)
}
function add() {
  if (!props.disabled && (!props.maxValues || rows.value.length < props.maxValues)) rows.value.push(blank())
}
function remove(index: number) {
  if (props.disabled) return
  rows.value.splice(index, 1)
  if (!rows.value.length) rows.value.push(blank())
  changed()
}
function token(row: Row): string | null {
  if (!row.material) return null
  const matches = props.options.filter((option) => option.label === row.material)
  return matches.length === 1 ? `option:${matches[0].value}` : `custom:${encodeURIComponent(row.material)}`
}
function materialOptions(row: Row): SelectOption[] {
  const options: SelectOption[] = props.options.map((option) => ({ label: option.label, value: `option:${option.value}` }))
  const selected = token(row)
  if (selected?.startsWith('custom:')) options.push({ label: row.material, value: selected })
  return options
}
function createOption(label: string): SelectOption {
  return { label: `添加『${label}』`, value: `custom:${encodeURIComponent(label)}`,
    __customCreate: true, __customLabel: label }
}
const renderLabel: SelectProps['renderLabel'] = (option, selected) => {
  const custom = option as SelectOption & { __customCreate?: boolean; __customLabel?: string }
  return custom.__customCreate && selected ? custom.__customLabel ?? String(custom.value ?? '') : String(custom.label ?? '')
}
function changeMaterial(row: Row, value: string | number | null) {
  const selected = String(value ?? '')
  const option = selected.startsWith('option:') ? props.options.find((item) => item.value === selected.slice(7)) : null
  row.material = option?.label ?? (selected.startsWith('custom:') ? decodeURIComponent(selected.slice(7)) : '')
  row.changed = true; changed()
}
function changeAmount(row: Row, value: string) { row.amount = value; row.changed = true; changed() }
function changeUnit(row: Row, value: string | number | null) {
  row.unit = String(value ?? ''); row.changed = true; changed()
}
</script>

<template>
  <div class="product-multi-measure">
    <div v-for="(row, index) in rows" :key="row.key" class="product-multi-measure__row">
      <AppInput v-if="row.raw" :model-value="row.raw" :aria-label="`${label} 原值 ${index + 1}`" readonly />
      <template v-else>
        <AppSelect :model-value="token(row)" :options="materialOptions(row)" :disabled="disabled"
          :aria-label="`${label} 材质 ${index + 1}`" filterable show-on-focus :tag="allowCustom"
          :on-create="allowCustom ? createOption : undefined" :render-label="renderLabel"
          @update:model-value="changeMaterial(row, $event)" />
        <AppInput :model-value="row.amount" :aria-label="`${label} 数值 ${index + 1}`" inputmode="decimal"
          :disabled="disabled" @update:model-value="changeAmount(row, $event)" />
        <AppSelect v-if="rule.units.length > 1" :model-value="row.unit"
          :options="rule.units.map((unit) => ({ label: unit.label, value: unit.label }))"
          :aria-label="`${label} 单位 ${index + 1}`" :disabled="disabled"
          @update:model-value="changeUnit(row, $event)" />
        <span v-else>{{ row.unit }}</span>
      </template>
      <AppButton size="small" :disabled="disabled" :aria-label="`删除${label}第 ${index + 1} 项`" @click="remove(index)">删除</AppButton>
    </div>
    <AppButton size="small" :disabled="disabled || (!!maxValues && rows.length >= maxValues)" @click="add">添加</AppButton>
  </div>
</template>

<style scoped>
.product-multi-measure { display:flex; flex-direction:column; align-items:flex-start; gap:var(--space-2); width:100%; }
.product-multi-measure__row { display:flex; align-items:center; flex-wrap:wrap; gap:var(--space-2); width:100%; }
.product-multi-measure__row :deep(.app-field) { flex:1 1 var(--field-width-xs); min-width:0; }
</style>
