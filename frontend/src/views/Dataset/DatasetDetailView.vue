<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { Dataset, DatasetField } from '@/types/security';
import DataPreviewTable from '@/components/common/DataPreviewTable.vue';
import { stripArffQuotes } from '@/utils/arffValue';
import { getDatasetDetail, getDatasetFields } from '@/api/datasetApi';

const route = useRoute();
const router = useRouter();
const datasetId = computed(() => String(route.params.datasetId ?? ''));
const loading = ref(true);
const error = ref('');
const notFound = ref(false);
const activeTab = ref(route.query.tab === 'preview' ? 'preview' : 'fields');
const dataset = ref<Dataset | null>(null);
const loadedFields = ref<DatasetField[] | null>(null);
const fields = computed(() => loadedFields.value ?? dataset.value?.fields ?? []);
const labelField = computed(() => fields.value.find((field) => field.field_role === '分类标签')?.field_name ?? '');

watch(() => route.query.tab, (tab) => {
  activeTab.value = tab === 'preview' ? 'preview' : 'fields';
});

watch(datasetId, async (id, _, onCleanup) => {
  let active = true;
  onCleanup(() => { active = false; });
  dataset.value = null;
  loadedFields.value = null;
  loading.value = true;
  error.value = '';
  notFound.value = false;
  if (!id) {
    loading.value = false;
    return;
  }
  try {
    const [detail, detailFields] = await Promise.all([getDatasetDetail(id), getDatasetFields(id)]);
    if (!active) return;
    dataset.value = detail;
    loadedFields.value = detailFields;
  } catch (err) {
    if (!active) return;
    if (String(err).includes('不存在')) notFound.value = true;
    else error.value = err instanceof Error ? err.message : '数据集加载失败';
  } finally {
    if (active) loading.value = false;
  }
}, { immediate: true, flush: 'sync' });
</script>

<template>
  <div class="dataset-detail">
    <section v-if="loading" class="card dataset-detail__head dataset-detail__head--loading">
      <div>
        <h2>正在加载数据集信息...</h2>
        <p class="dataset-detail__meta">字段结构较多时可能需要几秒，返回键不受影响</p>
      </div>
      <div class="dataset-detail__actions">
        <button
          class="dataset-detail__action dataset-detail__back"
          type="button"
          @click="router.back()"
        >返回</button>
      </div>
    </section>
    <section v-else-if="error || notFound" class="state-card" :class="{ 'state-card--error': error }">
      <p>{{ error || '数据集不存在' }}</p>
      <button class="ghost-button" @click="router.back()">返回</button>
    </section>

    <template v-else-if="dataset">
      <section class="card dataset-detail__head">
        <div>
          <h2>{{ dataset.name }}</h2>
          <p class="dataset-detail__meta">
            {{ dataset.data_format.toUpperCase() }} · 版本 {{ dataset.dataset_version }} ·
            {{ dataset.record_count.toLocaleString() }} 样本 · {{ dataset.field_count }} 字段
          </p>
        </div>
        <div class="dataset-detail__actions">
          <span
            class="dataset-detail__action dataset-detail__status"
            :class="{ 'is-disabled': !dataset.enabled }"
            role="status"
          >
            <span class="dataset-detail__status-dot" aria-hidden="true" />
            {{ dataset.enabled ? '已启用' : '已停用' }}
          </span>
          <button
            class="dataset-detail__action dataset-detail__back"
            type="button"
            @click="router.back()"
          >返回</button>
        </div>
      </section>

      <el-tabs v-model="activeTab" class="dataset-detail__tabs">
        <el-tab-pane label="字段结构" name="fields" lazy>
          <div class="dataset-detail__table-wrap">
            <el-table
              :data="fields"
              stripe
              style="width: 100%"
              empty-text="该数据集暂无字段信息"
            >
              <el-table-column prop="field_name" label="字段名" width="170" show-overflow-tooltip />
              <el-table-column prop="field_type" label="数据类型" width="110" align="center" />
              <el-table-column prop="field_role" label="字段角色" width="110" align="center">
                <template #default="{ row }: { row: { field_role: string } }">
                  <span
                    class="dataset-detail__role"
                    :class="row.field_role === '分类标签' ? 'is-label' : 'is-input'"
                  >{{ row.field_role }}</span>
                </template>
              </el-table-column>
              <el-table-column label="样例值" width="140" show-overflow-tooltip>
                <template
                  #default="{ row }: { row: { sample_value?: string } }"
                >{{ stripArffQuotes(row.sample_value) }}</template>
              </el-table-column>
              <el-table-column label="枚举值域" min-width="240" show-overflow-tooltip>
                <template #default="{ row }: { row: { enum_values?: string[] } }">
                  <span class="dataset-detail__enum">{{ row.enum_values?.map(stripArffQuotes).join(' / ') ?? '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="字段说明" width="88" align="center">
                <template #default="{ row }: { row: { description?: string } }">
                  <el-tooltip
                    v-if="row.description"
                    :content="row.description"
                    placement="top"
                    :show-after="120"
                  >
                    <span class="field-desc-dot field-desc-dot--on" />
                  </el-tooltip>
                  <span v-else class="field-desc-dot field-desc-dot--off" />
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
        <el-tab-pane label="数据内容预览" name="preview" lazy>
          <DataPreviewTable
            :datasetId="dataset.dataset_id"
            :labelField="labelField"
            :pageSize="50"
          />
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<style scoped>
.dataset-detail {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 18px;
}

.dataset-detail__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 26px;
}

.dataset-detail__head h2 {
  margin: 0 0 8px;
  font-size: 1.6rem;
  color: #c8deff;
}

.dataset-detail__meta {
  margin: 0;
  font-size: .95rem;
  color: rgba(180,200,235,.55);
}

.dataset-detail__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.dataset-detail__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: 34px;
  min-width: 72px;
  padding: 0 14px;
  border: 1px solid rgba(125,201,255,.35);
  border-radius: 8px;
  background: rgba(91,166,255,.1);
  color: #9ad6ff;
  font-size: .875rem;
  line-height: 1;
  white-space: nowrap;
}

.dataset-detail__status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #53e5c8;
  box-shadow: 0 0 0 3px rgba(83,229,200,.12);
  flex-shrink: 0;
}

.dataset-detail__status.is-disabled .dataset-detail__status-dot {
  background: rgba(180,200,235,.45);
  box-shadow: 0 0 0 3px rgba(180,200,235,.08);
}

.dataset-detail__back {
  cursor: pointer;
  transition: background-color .2s, border-color .2s, color .2s;
}

.dataset-detail__back:hover {
  border-color: rgba(91,166,255,.55);
  background: rgba(91,166,255,.18);
  color: #fff;
}

.dataset-detail__back:focus-visible {
  outline: 2px solid rgba(125,201,255,.65);
  outline-offset: 2px;
}

.dataset-detail__table-wrap {
  border: 1px solid rgba(125,201,255,.1);
  border-radius: 14px;
  overflow: hidden;
  background: rgba(8,18,34,.7);
}

.dataset-detail__role {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: .78rem;
}

.dataset-detail__role.is-label {
  background: rgba(83,229,200,.12);
  color: #53e5c8;
}

.dataset-detail__role.is-input {
  background: rgba(91,166,255,.12);
  color: #9ad6ff;
}

.dataset-detail__enum {
  font-size: .8rem;
  color: rgba(220,234,255,.65);
}

.field-desc-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  vertical-align: middle;
}

.field-desc-dot--on {
  background: #53e5c8;
  box-shadow: 0 0 0 3px rgba(83,229,200,.14);
  cursor: help;
}

.field-desc-dot--off { background: rgba(180,200,235,.22); }

@media (max-width: 768px) {
  .dataset-detail__head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>

<style>
.dataset-detail .el-table,
.dataset-detail .el-table__inner-wrapper,
.dataset-detail .el-table__body-wrapper,
.dataset-detail .el-table__header-wrapper {
  background-color: transparent !important;
}

.dataset-detail .el-table tr { background-color: var(--app-table-row-bg) !important; }

.dataset-detail .el-table th.el-table__cell {
  background-color: var(--app-table-header-bg) !important;
  color: rgba(155,195,240,.85) !important;
  font-weight: 600;
  border-bottom: 1px solid rgba(125,201,255,.08) !important;
}

.dataset-detail .el-table td.el-table__cell {
  background-color: var(--app-table-row-bg) !important;
  color: rgba(175,198,230,.85) !important;
  border-bottom: 1px solid rgba(125,201,255,.04) !important;
}

.dataset-detail .el-table__body tr:hover > td.el-table__cell {
  background-color: var(--app-table-row-hover-bg) !important;
}

.dataset-detail .el-table__empty-text { color: rgba(180,200,235,.3) !important; }

.dataset-detail .el-tabs__item { color: rgba(220,234,255,.65); }

.dataset-detail .el-tabs__item.is-active { color: #5ba6ff; }

.dataset-detail .el-tabs__active-bar { background-color: #5ba6ff; }

.dataset-detail .el-tabs__nav-wrap::after { background-color: rgba(125,201,255,.12); }
</style>
