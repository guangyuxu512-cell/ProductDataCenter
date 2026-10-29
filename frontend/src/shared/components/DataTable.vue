<script setup lang="ts">
import type {
  DataTableProps,
  DataTableRowKey,
  DataTableSortState,
} from 'naive-ui'

import AppTable from '@/shared/ui/AppTable.vue'

import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import LoadingState from './LoadingState.vue'

const props = withDefaults(
  defineProps<{
    columns: DataTableProps['columns']
    data?: DataTableProps['data']
    loading?: boolean
    error?: string | null
    rowKey?: DataTableProps['rowKey']
    scrollX?: number
    emptyDescription?: string
    showHeaderWhenEmpty?: boolean
    checkedRowKeys?: DataTableRowKey[]
    viewport?: 'auto' | 'stable' | 'fill'
    appearance?: 'grid' | 'list'
    themeOverrides?: DataTableProps['themeOverrides']
  }>(),
  {
    data: () => [],
    loading: false,
    error: null,
    rowKey: undefined,
    scrollX: undefined,
    emptyDescription: '暂无数据',
    showHeaderWhenEmpty: false,
    checkedRowKeys: () => [],
    viewport: 'auto',
    appearance: 'grid',
    themeOverrides: undefined,
  },
)

defineEmits<{
  retry: []
  'update:checkedRowKeys': [keys: DataTableRowKey[]]
  'update:sorter': [sorter: DataTableSortState | DataTableSortState[] | null]
}>()
</script>

<template>
  <div
    class="data-table"
    :class="[`data-table--${viewport}`, `data-table--appearance-${appearance}`]"
  >
    <LoadingState v-if="loading && (props.data?.length ?? 0) === 0" />
    <ErrorState
      v-else-if="error"
      :description="error"
      retryable
      @retry="$emit('retry')"
    />
    <EmptyState
      v-else-if="
        !loading && (props.data?.length ?? 0) === 0 && !showHeaderWhenEmpty
      "
      :description="emptyDescription"
    />
    <AppTable
      v-else
      :columns="columns"
      :data="data"
      :loading="loading"
      :row-key="rowKey"
      :scroll-x="scrollX"
      :checked-row-keys="checkedRowKeys"
      :appearance="appearance"
      :theme-overrides="themeOverrides"
      :fill="viewport === 'fill'"
      @update:checked-row-keys="$emit('update:checkedRowKeys', $event)"
      @update:sorter="$emit('update:sorter', $event)"
    >
      <template v-if="showHeaderWhenEmpty" #empty>
        <EmptyState :description="emptyDescription" />
      </template>
    </AppTable>
  </div>
</template>

<style scoped>
.data-table {
  min-width: 0;
}

.data-table--stable {
  min-height: var(--table-list-viewport-height);
}

.data-table--stable > :deep(.state-panel) {
  min-height: var(--table-list-viewport-height);
}

.data-table--fill {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.data-table--fill > :deep(.state-panel) {
  min-height: 0;
  flex: 1;
}
</style>
