<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import type { DataPreview } from '@/types/security';
import { getDatasetPreview } from '@/api/datasetApi';
import { attachOuterFirstWheel } from '@/utils/scrollChain';
import { keepScroll } from '@/utils/scrollAnchor';

const props = withDefaults(defineProps<{ datasetId: string; labelField: string; pageSize?: number }>(), { pageSize: 50 });
const currentPage = ref(1);
const loading = ref(true);
const error = ref('');
const preview = ref<DataPreview | null>(null);
let loadSequence = 0;
let mounted = true;
const rows = computed(() => preview.value?.rows ?? []);
const total = computed(() => preview.value?.total ?? 0);
const columns = computed(() => Object.keys(rows.value[0] ?? {}));

const loadPage = async (page: number, sequence = ++loadSequence) => {
  const pageSize = props.pageSize;
  const isCurrent = () => mounted && sequence === loadSequence;
  loading.value = true;
  error.value = '';
  try {
    let result = await getDatasetPreview(props.datasetId, { page, page_size: pageSize });
    if (!isCurrent()) return;
    const lastPage = Math.ceil(result.total / pageSize);
    if (!result.rows.length && result.total > 0 && lastPage < page) {
      result = await getDatasetPreview(props.datasetId, { page: lastPage, page_size: pageSize });
      if (!isCurrent()) return;
    }
    preview.value = result;
    currentPage.value = result.page;
  } catch (err) {
    if (isCurrent()) error.value = err instanceof Error ? err.message : '预览数据加载失败';
  } finally {
    if (isCurrent()) loading.value = false;
  }
};

const cellClass = ({ column }: { column: { property: string } }) => column.property === props.labelField ? 'preview-label-cell' : '';
const headerClass = ({ column }: { column: { property: string } }) => column.property === props.labelField ? 'preview-label-header' : '';

watch([() => props.datasetId, () => props.pageSize], ([id]) => {
  loadSequence += 1;
  preview.value = null;
  currentPage.value = 1;
  error.value = '';
  if (id) void loadPage(1);
  else loading.value = false;
}, { immediate: true, flush: 'sync' });

const tableWrapRef = ref<HTMLElement | null>(null);
let detachWheel: (() => void) | null = null;
watch(tableWrapRef, (element) => {
  detachWheel?.();
  detachWheel = element ? attachOuterFirstWheel(element) : null;
});
const changePage = (target: number) => {
  const sequence = ++loadSequence;
  return keepScroll(
    () => loadPage(target, sequence),
    tableWrapRef.value,
    () => mounted && sequence === loadSequence,
  );
};
onBeforeUnmount(() => {
  mounted = false;
  loadSequence += 1;
  detachWheel?.();
  detachWheel = null;
});
</script>

<template>
  <div class="data-preview">
    <div v-if="loading && !rows.length" class="data-preview__state">
      <div class="loader"></div>
      <p>正在加载数据内容...</p>
    </div>
    <div v-else-if="error" class="data-preview__state data-preview__state--error">
      <p>{{ error }}</p>
      <el-button size="small" plain @click="loadPage(currentPage)">重试</el-button>
    </div>
    <template v-else>
      <div ref="tableWrapRef" class="data-preview__table-wrap">
        <div v-if="loading" class="pane-loading"><div class="loader"></div></div>
        <el-table
          :data="rows"
          max-height="520"
          style="width: 100%"
          empty-text="暂无数据"
          :cell-class-name="cellClass"
          :header-cell-class-name="headerClass"
        >
          <el-table-column
            v-for="col in columns"
            :key="col"
            :prop="col"
            :label="col === labelField ? `${col}（标签）` : col"
            min-width="132"
            show-overflow-tooltip
          />
        </el-table>
      </div>
      <div class="data-preview__pager">
        <span class="data-preview__pager-total">共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="currentPage"
          layout="prev, pager, next"
          :page-size="pageSize"
          :total="total"
          background
          @current-change="changePage"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.data-preview {
  display: grid;
  gap: 12px;
}

.data-preview__state {
  display: grid;
  place-items: center;
  gap: 14px;
  padding: 56px 0;
}

.data-preview__state p {
  margin: 0;
  color: rgba(220,234,255,.65);
}

.data-preview__state--error p { color: #ff8c84; }

.data-preview__table-wrap {
  position: relative;
  border: 1px solid rgba(125,201,255,.1);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(8,18,34,.7);
}

.data-preview__pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.data-preview__pager-total {
  color: rgba(220,234,255,.6);
  font-size: .85rem;
}
</style>

<style>
.data-preview :is(.el-table, .el-table__inner-wrapper, .el-table__body-wrapper, .el-table__header-wrapper) {
  background-color: transparent !important;
}

.data-preview .el-table tr { background-color: var(--app-table-row-bg) !important; }

.data-preview .el-table th.el-table__cell {
  background-color: var(--app-table-header-bg) !important;
  color: rgba(155,195,240,.85) !important;
  font-weight: 600;
  border-bottom: 1px solid rgba(125,201,255,.08) !important;
}

.data-preview .el-table td.el-table__cell {
  background: var(--app-table-row-bg) !important;
  color: rgba(175,198,230,.85) !important;
  border-bottom: 1px solid rgba(125,201,255,.04) !important;
}

.data-preview .el-table__body tr:hover > td.el-table__cell { background-color: #142c48 !important; }

.data-preview .el-table .cell {
  padding: 0 10px;
  line-height: 1.5;
}

.data-preview .el-table th.el-table__cell > .cell { font-size: .8rem; }

.data-preview .el-table td.el-table__cell > .cell {
  font-size: .82rem;
  font-variant-numeric: tabular-nums;
}

.data-preview .el-table__empty-text { color: rgba(180,200,235,.3) !important; }

.data-preview .preview-label-header {
  color: #ffd166 !important;
  background-color: rgba(255,209,102,.1) !important;
}

.data-preview .preview-label-cell {
  background-color: rgba(255,209,102,.14) !important;
  color: #ffd166 !important;
  font-weight: 600;
}

.data-preview .el-pagination {
  --el-pagination-bg-color: rgba(8,17,31,.8);
  --el-pagination-button-bg-color: rgba(12,26,46,.9);
  --el-pagination-button-disabled-bg-color: rgba(8,17,31,.45);
  --el-pagination-text-color: rgba(220,234,255,.75);
  --el-pagination-button-color: rgba(220,234,255,.75);
  --el-pagination-button-disabled-color: rgba(180,200,235,.28);
  --el-pagination-hover-color: #5ba6ff;
}

.data-preview .el-pagination.is-background :is(.el-pager li, .btn-prev, .btn-next) {
  border: 1px solid rgba(125,201,255,.12);
  border-radius: 6px;
}

.data-preview .el-pagination.is-background :is(.el-pager li:not(.is-active):hover, .btn-prev:hover, .btn-next:hover) {
  background-color: rgba(20,44,72,.95) !important;
  color: #9ad6ff !important;
}

.data-preview .el-pagination.is-background .el-pager li.is-active {
  background-color: #3f7fd4 !important;
  color: #fff !important;
  border-color: transparent;
}

.data-preview .el-pagination.is-background :is(.btn-prev, .btn-next) {
  background-color: rgba(12,26,46,.9) !important;
  color: rgba(220,234,255,.7) !important;
}

.data-preview .el-pagination.is-background :is(.btn-prev, .btn-next):disabled {
  background-color: rgba(8,17,31,.45) !important;
  color: rgba(180,200,235,.25) !important;
}
</style>
