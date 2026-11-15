<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NCard, NFormItem, NSpace, NSwitch, NText, useMessage } from 'naive-ui'
import { AppButton, AppDialog, AppSelect } from '@/shared/ui'
import { fetchPrecheckGroupRules, savePrecheckGroupRules, type PrecheckGroupRule } from '../api/products'
import type { ProductGroup } from '../model/nas-contracts'

const props = defineProps<{ show: boolean; groups: ProductGroup[] }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()
const message = useMessage()
const loading = ref(false), saving = ref(false), version = ref(0)
const rules = ref<PrecheckGroupRule[]>([])
const sourceOptions = computed(() => [
  { label: '全部商品', value: 'all' }, { label: '未分组商品', value: 'ungrouped' },
  ...props.groups.map((group) => ({ label: group.name, value: group.groupId })),
])
const targetOptions = computed(() => [
  { label: '保持原分组', value: 'keep' }, { label: '未分组', value: 'ungrouped' },
  ...props.groups.map((group) => ({ label: group.name, value: group.groupId })),
])

watch(() => props.show, async (show) => {
  if (!show) return
  loading.value = true
  try {
    const config = await fetchPrecheckGroupRules()
    version.value = config.version
    rules.value = config.rules.map((rule) => ({ ...rule }))
  } catch (error) {
    message.error(error instanceof Error ? error.message : '读取自动分组规则失败')
    emit('update:show', false)
  } finally { loading.value = false }
})

function addRule() {
  rules.value.push({ id: crypto.randomUUID(), enabled: true, source: 'ungrouped', passed: 'keep', incomplete: 'keep' })
}

async function save() {
  if (saving.value || loading.value) return
  if (rules.value.some((rule) => rule.enabled && rule.passed === 'keep' && rule.incomplete === 'keep')) {
    message.error('启用规则时请至少选择一个目标分组'); return
  }
  const sources = rules.value.filter((rule) => rule.enabled).map((rule) => rule.source)
  if (new Set(sources).size !== sources.length) {
    message.error('同一来源分组只能启用一条规则'); return
  }
  saving.value = true
  try {
    const saved = await savePrecheckGroupRules({ version: version.value, rules: rules.value })
    version.value = saved.version
    message.success('自动分组规则已保存')
    emit('update:show', false)
  } catch (error) { message.error(error instanceof Error ? error.message : '保存自动分组规则失败') }
  finally { saving.value = false }
}
</script>

<template>
  <AppDialog :show="show" title="预检自动分组" size="lg" positive-text="保存规则"
    :loading="saving" :positive-disabled="loading || saving" @update:show="!saving && emit('update:show', $event)" @confirm="save">
    <NSpace vertical>
      <NText depth="3">规则只处理启用后完成的预检。预检失败或设备不可用时不会移动商品；指定来源分组的规则优先于全部商品规则。</NText>
      <NText v-if="!rules.length && !loading" depth="3">还没有自动分组规则。</NText>
      <NCard v-for="(rule, index) in rules" :key="rule.id" size="small" :title="`规则 ${index + 1}`">
        <template #header-extra>
          <NSpace align="center"><span>启用</span><NSwitch v-model:value="rule.enabled" :aria-label="`启用规则 ${index + 1}`" />
            <AppButton tone="danger" size="small" @click="rules.splice(index, 1)">删除</AppButton></NSpace>
        </template>
        <NFormItem label="来源商品"><AppSelect v-model="rule.source" :options="sourceOptions" filterable aria-label="来源商品" /></NFormItem>
        <NFormItem label="预检通过"><AppSelect v-model="rule.passed" :options="targetOptions" filterable aria-label="预检通过后移动到" /></NFormItem>
        <NFormItem label="待完善或待选择类目"><AppSelect v-model="rule.incomplete" :options="targetOptions" filterable aria-label="未通过后移动到" /></NFormItem>
      </NCard>
      <AppButton :disabled="loading || saving" @click="addRule">添加规则</AppButton>
    </NSpace>
  </AppDialog>
</template>
