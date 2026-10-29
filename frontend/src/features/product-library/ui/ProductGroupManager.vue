<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { NForm, NFormItem, useDialog, useMessage, type DataTableColumns } from 'naive-ui'
import { AppButton, AppDialog, AppInput } from '@/shared/ui'
import { DataTable } from '@/shared/components'
import { saveGroup, deleteGroup } from '../api/products'
import type { ProductGroup } from '../model/nas-contracts'

const props = defineProps<{ show: boolean; groups: ProductGroup[]; writable: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean]; changed: [] }>()
const message = useMessage(), dialog = useDialog()
const name = ref(''), editingId = ref<string | undefined>(), saving = ref(false)
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败'

async function submit() {
  if (!props.writable || saving.value) return
  if (!name.value.trim()) { message.error('请输入分组名称'); return }
  saving.value = true
  try {
    await saveGroup(name.value.trim(), editingId.value)
    message.success(editingId.value ? '分组已重命名' : '分组已创建')
    name.value = ''; editingId.value = undefined
    emit('changed')
  } catch (error) { message.error(errorText(error)) }
  finally { saving.value = false }
}

function remove(group: ProductGroup) {
  if (!props.writable || saving.value) return
  dialog.warning({ title: '删除分组', content: `删除“${group.name}”？其中商品将保留并变为未分组。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      saving.value = true
      try {
        await deleteGroup(group.groupId)
        if (editingId.value === group.groupId) { editingId.value = undefined; name.value = '' }
        message.success('分组已删除'); emit('changed')
      } catch (error) { message.error(errorText(error)); return false }
      finally { saving.value = false }
    },
  })
}

const columns = computed<DataTableColumns<ProductGroup>>(() => [
  { title: '分组名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '商品数量', key: 'productCount', align: 'center', width: 110 },
  { title: '操作', key: 'actions', align: 'center', width: 170, render: (row) => h('div', { class: 'product-library-actions' }, [
    h(AppButton, { tone: 'link', size: 'small', disabled: !props.writable || saving.value,
      onClick: () => { editingId.value = row.groupId; name.value = row.name } }, () => '重命名'),
    h(AppButton, { tone: 'danger', size: 'small', disabled: !props.writable || saving.value,
      onClick: () => remove(row) }, () => '删除'),
  ]) },
])
</script>

<template>
  <AppDialog :show="show" title="分组管理" size="lg" positive-text="关闭" :show-negative="false"
    @update:show="emit('update:show', $event)" @confirm="emit('update:show', false)">
    <NForm inline @submit.prevent="submit">
      <NFormItem :label="editingId ? '重命名' : '新建分组'">
        <AppInput v-model="name" aria-label="分组名称" :maxlength="80" :disabled="!writable || saving" @keyup.enter="submit" />
      </NFormItem>
      <NFormItem>
        <AppButton tone="primary" :loading="saving" :disabled="!writable" @click="submit">{{ editingId ? '保存' : '新增' }}</AppButton>
      </NFormItem>
      <NFormItem v-if="editingId"><AppButton @click="editingId = undefined; name = ''">取消</AppButton></NFormItem>
    </NForm>
    <DataTable :columns="columns" :data="groups" :row-key="(row: ProductGroup) => row.groupId" viewport="stable" />
  </AppDialog>
</template>
