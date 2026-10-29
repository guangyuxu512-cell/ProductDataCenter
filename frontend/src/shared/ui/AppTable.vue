<script setup lang="ts">
import { NDataTable } from 'naive-ui'
import type {
  DataTableProps,
  DataTableRowData,
  DataTableRowKey,
  DataTableSortState,
} from 'naive-ui'

const props = withDefaults(
  defineProps<{
    columns: DataTableProps['columns']
    data?: DataTableProps['data']
    loading?: boolean
    bordered?: boolean
    striped?: boolean
    rowKey?: DataTableProps['rowKey']
    scrollX?: number
    checkedRowKeys?: DataTableRowKey[]
    appearance?: 'grid' | 'list'
    fill?: boolean
    themeOverrides?: DataTableProps['themeOverrides']
  }>(),
  {
    data: () => [],
    loading: false,
    bordered: false,
    striped: false,
    rowKey: undefined,
    scrollX: undefined,
    checkedRowKeys: () => [],
    appearance: 'grid',
    fill: false,
    themeOverrides: undefined,
  },
)

const emit = defineEmits<{
  'update:checkedRowKeys': [keys: DataTableRowKey[]]
  'update:sorter': [
    sorter: DataTableSortState | DataTableSortState[] | null,
  ]
}>()

function rowClassName(row: DataTableRowData): string {
  if (!props.rowKey) return ''
  const key = props.rowKey(row)
  return props.checkedRowKeys.includes(key) ? 'app-table__row--selected' : ''
}

function handleSorterUpdate(
  sorter: DataTableSortState | DataTableSortState[] | null,
): void {
  emit('update:sorter', sorter)
}
</script>

<template>
  <NDataTable
    class="app-table"
    :class="[`app-table--${appearance}`, { 'app-table--fill': fill }]"
    size="medium"
    :columns="columns"
    :data="data"
    :loading="loading"
    :bordered="bordered"
    :striped="striped"
    :row-key="rowKey"
    :scroll-x="scrollX"
    :checked-row-keys="props.checkedRowKeys"
    :theme-overrides="props.themeOverrides"
    :row-class-name="rowClassName"
    :single-line="false"
    :flex-height="fill"
    @update:checked-row-keys="$emit('update:checkedRowKeys', $event)"
    @update:sorter="handleSorterUpdate"
  >
    <template v-if="$slots.empty" #empty>
      <slot name="empty" />
    </template>
  </NDataTable>
</template>

<style scoped>
.app-table--list :deep(.n-data-table-th),
.app-table--list :deep(.n-data-table-td) {
  text-align: center;
}

.app-table--list
  :deep(.n-data-table-tr.app-table__row--selected .n-data-table-td) {
  background-color: var(--color-primary-soft);
}

.app-table--fill {
  min-height: 0;
  flex: 1;
}
</style>
