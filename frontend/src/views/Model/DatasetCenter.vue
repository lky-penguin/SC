<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { formatBeijingDateTime, parseInstant } from '@/utils/datetime';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import type { Dataset, DatasetVersion } from '@/types/security';
import {
  getDatasetList, getDatasetVersions, uploadDatasetFile, appendDatasetRows,
  getDatasetRevisions, disableDatasetVersion, deleteDatasetVersion,
  getDatasetAiAnalysis, streamDatasetAiAnalysis,
} from '@/api/datasetApi';
import type { DatasetRevisionItem } from '@/api/datasetApi';

const router = useRouter();
const formatRevisionTime = (value?: string | null) => {
  const ms = parseInstant(value);
  return ms ? formatBeijingDateTime(ms) : '—';
};
const FORMAT_LABEL: Record<Dataset['data_format'], string> = { csv: 'CSV', arff: 'ARFF', json: 'JSON' };
const allDatasets = ref<Dataset[]>([]);
const loading = ref(true);
const error = ref('');
let datasetRequestId = 0;

const uploadDialogVisible = ref(false);
const uploadForm = ref({ name: '' });
const selectedFile = ref<File | null>(null);
const uploadFileInputRef = ref<HTMLInputElement | null>(null);
const appendFileInputRef = ref<HTMLInputElement | null>(null);

const pickFile = (input: HTMLInputElement | null) => {
  if (!input) return;
  input.value = '';
  input.click();
};
const onFileChange = (event: Event) => {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
};
const openUploadDialog = () => {
  uploadForm.value = { name: '' };
  selectedFile.value = null;
  uploadDialogVisible.value = true;
};
const submitNewDataset = async () => {
  if (!uploadForm.value.name.trim()) return void ElMessage.warning('请填写态势感知数据集名称');
  if (!selectedFile.value) return void ElMessage.warning('请选择要上传的 ARFF / CSV 文件');
  try {
    await uploadDatasetFile({
      file: selectedFile.value,
      name: uploadForm.value.name.trim(),
    });
    ElMessage.success('数据集上传成功');
    uploadDialogVisible.value = false;
    await loadDatasets();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '上传失败');
  }
};

const appendDialogVisible = ref(false);
const appendTarget = ref<Dataset | null>(null);
const appendFile = ref<File | null>(null);
const appendSubmitting = ref(false);
const openAppendDialog = (dataset: Dataset) => {
  appendTarget.value = dataset;
  appendFile.value = null;
  appendSubmitting.value = false;
  appendDialogVisible.value = true;
};
const onAppendFileChange = (event: Event) => {
  appendFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
};
const submitAppend = async () => {
  const target = appendTarget.value;
  if (!target) return;
  if (!appendFile.value) return void ElMessage.warning('请选择要追加的增量文件（.arff / .csv）');
  appendSubmitting.value = true;
  try {
    const version = await appendDatasetRows(target.dataset_id, appendFile.value);
    const rows = version.record_count.toLocaleString();
    ElMessage.success(version.dataset_version === target.dataset_version
      ? `追加成功：已并入 ${version.dataset_version}，共 ${rows} 条`
      : `追加成功：已新建版本 ${version.dataset_version}，共 ${rows} 条`);
    appendDialogVisible.value = false;
    await refreshVersionData();
    await loadDatasets();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '追加失败');
  } finally {
    appendSubmitting.value = false;
  }
};

const versionDialogVisible = ref(false);
const versionDialogTitle = ref('');
const versionTarget = ref<Dataset | null>(null);
const versionList = ref<DatasetVersion[]>([]);
const versionLoading = ref(false);
const revisionList = ref<DatasetRevisionItem[]>([]);
let versionRequestId = 0;
const isCurrentVersionRequest = (requestId: number, datasetId: string) =>
  requestId === versionRequestId && versionDialogVisible.value && versionTarget.value?.dataset_id === datasetId;
const loadVersionDialogData = async (datasetId: string, requestId = ++versionRequestId) => {
  const isCurrent = () => isCurrentVersionRequest(requestId, datasetId);
  if (!isCurrent()) return;
  versionLoading.value = true;
  try {
    const [versions, revisions] = await Promise.allSettled([getDatasetVersions(datasetId), getDatasetRevisions(datasetId)]);
    if (!isCurrent()) return;
    versionList.value = versions.status === 'fulfilled' ? versions.value : [];
    revisionList.value = revisions.status === 'fulfilled' ? revisions.value : [];
  } finally {
    if (isCurrent()) versionLoading.value = false;
  }
};
const refreshVersionData = async () => {
  if (versionTarget.value && versionDialogVisible.value) {
    await loadVersionDialogData(versionTarget.value.dataset_id);
  }
};
const closeVersionDialog = () => {
  versionRequestId += 1;
  versionLoading.value = false;
};
const openVersionDialog = async (dataset: Dataset) => {
  const requestId = ++versionRequestId;
  versionTarget.value = dataset;
  versionDialogTitle.value = `版本管理 - ${dataset.name}`;
  versionList.value = [];
  revisionList.value = [];
  versionDialogVisible.value = true;
  await loadVersionDialogData(dataset.dataset_id, requestId);
};
const handleDisableVersion = async (version: DatasetVersion) => {
  try {
    await disableDatasetVersion(version.dataset_version_id);
    ElMessage.success(`版本 ${version.dataset_version} 已停用`);
    await refreshVersionData();
    await loadDatasets();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '停用失败');
  }
};
const handleDeleteVersion = async (version: DatasetVersion) => {
  try {
    await deleteDatasetVersion(version.dataset_version_id);
    ElMessage.success(`版本 ${version.dataset_version} 已删除`);
    await refreshVersionData();
    await loadDatasets();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '删除失败');
  }
};

const loadDatasets = async () => {
  const requestId = ++datasetRequestId;
  loading.value = true;
  error.value = '';
  try {
    const rows = await getDatasetList();
    if (requestId === datasetRequestId) allDatasets.value = rows;
  } catch (err) {
    if (requestId === datasetRequestId) error.value = err instanceof Error ? err.message : '数据集加载失败';
  } finally {
    if (requestId === datasetRequestId) loading.value = false;
  }
};

const aiDialogVisible = ref(false);
const aiDialogTitle = ref('');
const aiDialogLoading = ref(false);
const aiDialogLoaded = ref(false);
const aiDialogStatus = ref('');
const aiDialogError = ref('');
const aiDialogReasoning = ref('');
const aiDialogMarkdown = ref('');
const aiDialogDatasetId = ref<string | number>('');
const aiBodyRef = ref<HTMLElement | null>(null);
const aiReasoningRef = ref<HTMLElement | null>(null);
let aiAbort: AbortController | null = null;
let aiRequestId = 0;
const isCurrentAi = (requestId: number) => requestId === aiRequestId;
const aiDialogHtml = computed(() => aiDialogMarkdown.value
  ? DOMPurify.sanitize(marked.parse(aiDialogMarkdown.value, { async: false }) as string)
  : '');
const stickAiToBottom = () => {
  if (!aiDialogLoading.value) return;
  void nextTick(() => {
    const body = aiBodyRef.value?.closest('.el-dialog__body') as HTMLElement | null;
    for (const element of [body, aiReasoningRef.value]) if (element) element.scrollTop = element.scrollHeight;
  });
};
watch([aiDialogReasoning, aiDialogMarkdown], stickAiToBottom);

const loadAiAnalysis = async () => {
  const datasetId = aiDialogDatasetId.value;
  if (!datasetId || aiDialogLoaded.value) return;
  const requestId = ++aiRequestId;
  aiDialogStatus.value = '';
  aiDialogError.value = '';
  try {
    const response = await getDatasetAiAnalysis(datasetId);
    if (!isCurrentAi(requestId)) return;
    if (response.available && response.markdown) {
      aiDialogMarkdown.value = response.markdown;
      aiDialogReasoning.value = '';
    }
  } catch (err) {
    if (!isCurrentAi(requestId)) return;
    aiDialogError.value = err instanceof Error ? err.message : '读取解析结果失败';
  } finally {
    if (isCurrentAi(requestId)) aiDialogLoaded.value = true;
  }
};
const runAiAnalysis = async (regenerate = false) => {
  if (!aiDialogDatasetId.value || aiDialogLoading.value) return;
  const requestId = ++aiRequestId;
  aiAbort?.abort();
  const controller = new AbortController();
  aiAbort = controller;
  aiDialogLoading.value = true;
  aiDialogError.value = '';
  aiDialogReasoning.value = '';
  if (regenerate) aiDialogMarkdown.value = '';
  aiDialogStatus.value = regenerate ? '正在重新解析数据集...' : '正在解析数据集...';
  try {
    await streamDatasetAiAnalysis(aiDialogDatasetId.value, {
      onStart: (data) => { if (isCurrentAi(requestId)) aiDialogStatus.value = String(data.status ?? '正在解析数据集...'); },
      onReasoning: (content) => { if (isCurrentAi(requestId)) aiDialogReasoning.value += content; },
      onDelta: (content) => {
        if (!isCurrentAi(requestId)) return;
        if (aiDialogReasoning.value) aiDialogReasoning.value = '';
        aiDialogMarkdown.value += content;
      },
      onError: (message) => { if (isCurrentAi(requestId)) aiDialogError.value = message; },
      onDone: () => {
        if (!isCurrentAi(requestId)) return;
        aiDialogStatus.value = ''; aiDialogLoaded.value = true; stickAiToBottom();
      },
    }, controller.signal, regenerate);
  } catch (err) {
    if (!isCurrentAi(requestId) || (err as { name?: string })?.name === 'AbortError') return;
    aiDialogError.value = err instanceof Error ? err.message : 'AI 解析失败';
    aiDialogStatus.value = ''; aiDialogReasoning.value = '';
  } finally {
    if (isCurrentAi(requestId)) {
      aiDialogLoading.value = false; aiAbort = null;
    }
  }
};
const openAiAnalysis = (dataset: Dataset) => {
  aiRequestId += 1;
  aiAbort?.abort();
  aiAbort = null;
  aiDialogTitle.value = `AI 解析 - ${dataset.name}`;
  aiDialogDatasetId.value = dataset.dataset_id;
  aiDialogLoading.value = false;
  aiDialogLoaded.value = false;
  aiDialogStatus.value = '';
  aiDialogError.value = '';
  aiDialogReasoning.value = '';
  aiDialogMarkdown.value = '';
  aiDialogVisible.value = true;
  void loadAiAnalysis();
};
const closeAiAnalysis = () => {
  aiRequestId += 1;
  aiAbort?.abort();
  aiAbort = null;
  aiDialogLoading.value = false;
};
const goDatasetDetail = (dataset: Dataset, tab: 'fields' | 'preview') => {
  router.push({ path: `/datasets/${dataset.dataset_id}`, query: { tab } });
};

onMounted(() => { void loadDatasets(); });
onBeforeUnmount(() => {
  datasetRequestId += 1; versionRequestId += 1; closeAiAnalysis();
});
</script>

<template>
  <div class="dataset-center">
    <div class="dataset-center__toolbar">
      <span class="dataset-center__count">共 <strong>{{ allDatasets.length }}</strong> 个数据集</span>
      <button class="upload-btn" @click="openUploadDialog">+ 上传数据集</button>
    </div>

    <section v-if="loading" class="state-card">
      <div class="loader"></div>
      <p>正在加载数据集...</p>
    </section>
    <section v-else-if="error" class="state-card state-card--error">
      <p>{{ error }}</p>
      <button class="ghost-button" @click="loadDatasets">重试</button>
    </section>
    <div v-else class="dataset-center__table-wrap">
      <el-table
        :data="allDatasets"
        stripe
        style="width: 100%"
        empty-text="暂无数据集"
        row-class-name="dataset-table-row"
      >
        <el-table-column prop="name" label="态势感知数据集名称" min-width="190" show-overflow-tooltip>
          <template #default="{ row }: { row: Dataset }">
            <span class="dataset-table__name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="data_format" label="格式" width="80" align="center">
          <template #default="{ row }: { row: Dataset }">
            <span
              class="format-badge"
              :class="`format-badge--${row.data_format}`"
            >{{ FORMAT_LABEL[row.data_format] ?? row.data_format.toUpperCase() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="record_count" label="数据量" width="100" align="right" sortable>
          <template #default="{ row }: { row: Dataset }">
            <span class="dataset-table__number">{{ row.record_count.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="field_count" label="字段数" width="100" align="center" sortable />
        <el-table-column label="版本" width="110" align="center">
          <template #default="{ row }: { row: Dataset }">
            <span
              class="version-badge"
              :class="row.enabled ? 'version-badge--on' : 'version-badge--off'"
            >{{ row.dataset_version }}{{ row.enabled ? '' : '（停用）' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="120" align="center">
          <template #default="{ row }: { row: Dataset }">
            <span class="dataset-table__time">{{ row.created_at.slice(0, 10) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" align="center" fixed="right">
          <template #default="{ row }: { row: Dataset }">
            <div class="dataset-ops">
              <el-button size="small" plain @click="goDatasetDetail(row, 'fields')">字段预览</el-button>
              <el-button size="small" plain @click="goDatasetDetail(row, 'preview')">数据预览</el-button>
              <el-button size="small" plain @click="openAiAnalysis(row)">AI解析</el-button>
              <el-button size="small" plain @click="openVersionDialog(row)">版本管理</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="aiDialogVisible" :title="aiDialogTitle" width="760px" top="6vh" append-to-body
      class="ai-analysis-dialog" :close-on-click-modal="false" @close="closeAiAnalysis"
    >
      <div ref="aiBodyRef" class="ai-analysis">
        <div v-if="aiDialogError" class="ai-analysis__notice ai-analysis__notice--error">{{ aiDialogError }}</div>
        <div v-if="aiDialogStatus" class="ai-analysis__status">{{ aiDialogStatus }}</div>
        <div v-if="aiDialogReasoning" class="ai-analysis__reasoning">
          <div class="ai-analysis__reasoning-label">模型推理中</div>
          <div ref="aiReasoningRef" class="ai-analysis__reasoning-text">{{ aiDialogReasoning }}</div>
        </div>
        <div v-if="aiDialogHtml" class="ai-analysis__markdown" v-html="aiDialogHtml"></div>
        <div v-else-if="!aiDialogLoading && !aiDialogReasoning && !aiDialogStatus" class="ai-analysis__empty">
          暂无解析。点击「解析」调用 AI，判断该数据集适合使用的算法。
        </div>
      </div>
      <template #footer>
        <el-button @click="aiDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="aiDialogLoading" @click="runAiAnalysis(Boolean(aiDialogMarkdown))">
          {{ aiDialogMarkdown ? '重新解析' : '解析' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="uploadDialogVisible"
      title="上传数据集"
      width="680px"
      top="6vh"
      append-to-body
      :close-on-click-modal="false"
    >
      <div class="upload-form">
        <div class="upload-form__row">
          <label class="upload-form__label">态势感知数据集名称<span class="required">*</span></label>
          <input
            v-model.trim="uploadForm.name"
            class="upload-form__input"
            placeholder="如 网络流量风险数据集"
          />
        </div>
        <div class="upload-form__row">
          <label class="upload-form__label">数据文件<span class="required">*</span>（.arff / .csv）</label>
          <div class="upload-picker">
            <input
              ref="uploadFileInputRef"
              type="file"
              accept=".arff,.csv"
              class="upload-picker__input"
              @change="onFileChange"
            />
            <button
              class="upload-icon-btn"
              type="button"
              aria-label="选择数据文件"
              @click="pickFile(uploadFileInputRef)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M12 13v8" /><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" /><path d="m8 17 4-4 4 4" />
              </svg>
            </button>
            <span
              class="upload-picker__name"
              :class="{ 'is-empty': !selectedFile }"
            >
              {{ selectedFile ? `${selectedFile.name}（${(selectedFile.size / 1024).toFixed(1)} KB）` : '未选择文件' }}
            </span>
          </div>
        </div>
        <p class="upload-form__hint">系统将自动识别最后一列为标签字段。</p>
      </div>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitNewDataset">确认上传</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="versionDialogVisible"
      :title="versionDialogTitle"
      class="version-dialog"
      width="1100px"
      align-center
      append-to-body
      :close-on-click-modal="false"
      @close="closeVersionDialog"
    >
      <div class="version-dialog-toolbar">
        <el-button v-if="versionTarget" size="small" plain @click="openAppendDialog(versionTarget)">追加数据</el-button>
      </div>
      <el-table
        :data="versionList"
        class="version-dialog__table"
        max-height="var(--version-pane-max-h)"
        stripe
        style="width: 100%"
        :empty-text="versionLoading ? '加载中…' : '暂无版本记录'"
      >
        <el-table-column prop="dataset_version" label="版本" min-width="80" align="center">
          <template #default="{ row }: { row: DatasetVersion }">
            <span
              class="version-badge"
              :class="row.enabled ? 'version-badge--on' : 'version-badge--off'"
            >{{ row.dataset_version }}</span>
          </template>
        </el-table-column>
        <el-table-column label="变更类型" min-width="150" align="center">
          <template #default="{ row }: { row: DatasetVersion }">
            <span v-if="row.change_type_label" class="iteration-tag">
              {{ row.change_type_label }}
              <span
                v-if="row.is_breaking"
                class="iteration-tag__flag iteration-tag__flag--breaking"
                title="破坏结构兼容：旧模型不可直接复用"
              >不兼容</span>
              <span
                v-else
                class="iteration-tag__flag iteration-tag__flag--compatible"
                title="兼容变更：旧模型仍可使用"
              >兼容</span>
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="record_count" label="样本数" min-width="100" align="right">
          <template #default="{ row }: { row: DatasetVersion }">
            {{ row.record_count.toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column prop="field_count" label="字段数" min-width="90" align="center" />
        <el-table-column prop="uploaded_at" label="上传时间" min-width="180" />
        <el-table-column prop="referenced" label="引用" min-width="90" align="center">
          <template #default="{ row }: { row: DatasetVersion }">
            <span :class="row.referenced ? 'text-active' : 'text-muted'">{{ row.referenced ? '是' : '否' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="150" align="center">
          <template #default="{ row }: { row: DatasetVersion }">
            <div class="dataset-ops">
              <el-button
                v-if="row.enabled"
                size="small"
                plain
                @click="handleDisableVersion(row)"
              >停用</el-button>
              <el-button
                v-if="!row.referenced"
                size="small"
                type="danger"
                plain
                @click="handleDeleteVersion(row)"
              >删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="revision-history__title">迭代记录</div>
      <div class="revision-history">
        <p v-if="versionLoading" class="version-tip">加载中…</p>
        <p v-else-if="revisionList.length === 0" class="version-tip">暂无迭代记录</p>
        <ul v-else class="revision-history__list">
          <li v-for="item in revisionList" :key="item.id" class="revision-history__item">
            <span class="revision-history__time">
              {{ formatRevisionTime(item.created_at) }}
            </span>
            <span class="iteration-tag">
              {{ item.change_type_label }}
              <span v-if="item.is_breaking" class="iteration-tag__flag iteration-tag__flag--breaking">不兼容</span>
              <span v-else class="iteration-tag__flag iteration-tag__flag--compatible">兼容</span>
            </span>
            <span class="revision-history__mode">{{ item.mode === 'new_version' ? '新建版本' : '原地更新' }}</span>
            <span class="revision-history__summary">{{ item.summary || item.reason || '—' }}</span>
          </li>
        </ul>
      </div>
    </el-dialog>

    <el-dialog
      v-model="appendDialogVisible"
      :title="`追加数据 - ${appendTarget?.name ?? ''}`"
      width="560px"
      align-center
      append-to-body
      :close-on-click-modal="false"
    >
      <div class="upload-form">
        <p class="version-tip">
          增量文件须与当前数据集字段同名、同序且格式一致。未被模型引用时原地追加，版本不变；已被引用时自动新建版本并保留旧版本。
        </p>
        <div class="upload-form__row">
          <label class="upload-form__label">增量文件<span class="required">*</span>（.arff / .csv）</label>
          <div class="upload-picker">
            <input
              ref="appendFileInputRef"
              type="file"
              accept=".arff,.csv"
              class="upload-picker__input"
              @change="onAppendFileChange"
            />
            <button
              class="upload-icon-btn"
              type="button"
              aria-label="选择增量文件"
              @click="pickFile(appendFileInputRef)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M12 13v8" /><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" /><path d="m8 17 4-4 4 4" />
              </svg>
            </button>
            <span
              class="upload-picker__name"
              :class="{ 'is-empty': !appendFile }"
            >
              {{ appendFile ? `${appendFile.name}（${(appendFile.size / 1024).toFixed(1)} KB）` : '未选择文件' }}
            </span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="appendDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="appendSubmitting"
          @click="submitAppend"
        >确认追加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dataset-center {
  position: relative;
  z-index: 1;
}

.dataset-center__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.dataset-center__count {
  font-size: .88rem;
  color: rgba(220,234,255,.6);
  white-space: nowrap;
}

.dataset-center__count strong { color: #9ad6ff; }

.dataset-center__table-wrap {
  border: 1px solid rgba(125,201,255,.1);
  border-radius: 18px;
  overflow: hidden;
  background: rgba(8,18,34,.7);
}

.dataset-table-row { background: transparent !important; }

.dataset-table__name {
  font-weight: 600;
  color: #c8deff;
  font-size: .95rem;
}

.dataset-table__number {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #b8ceef;
}

.dataset-table__time {
  font-size: .85rem;
  color: rgba(220,234,255,.65);
}

.ai-analysis__status,
.ai-analysis__notice,
.ai-analysis__empty {
  margin-bottom: 14px;
  padding: 10px 12px;
  border-radius: 7px;
  background: rgba(91,166,255,.08);
  color: rgba(220,234,255,.72);
  font-size: .84rem;
}

.ai-analysis__notice--error {
  background: rgba(255,123,114,.1);
  color: #ffaaa3;
}

.ai-analysis__reasoning {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(125,201,255,.14);
  border-radius: 8px;
  background: rgba(10,22,40,.5);
}

.ai-analysis__reasoning-label {
  margin-bottom: 6px;
  color: rgba(154,214,255,.72);
  font-size: .78rem;
}

.ai-analysis__reasoning-text {
  max-height: 200px;
  overflow: auto;
  color: rgba(196,214,240,.66);
  font-size: .85rem;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.ai-analysis__markdown {
  padding-top: 4px;
  color: rgba(232,241,255,.88);
  font-size: .9rem;
  line-height: 1.7;
}

.ai-analysis__markdown :deep(h1),
.ai-analysis__markdown :deep(h2),
.ai-analysis__markdown :deep(h3) {
  margin: 16px 0 8px;
  color: #d9e8ff;
  font-size: 1rem;
}

.ai-analysis__markdown :deep(p),
.ai-analysis__markdown :deep(ul),
.ai-analysis__markdown :deep(ol) {
  margin: 7px 0;
}

.ai-analysis__markdown :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
  background: rgba(8,17,31,.65);
  color: #9ad6ff;
  font-family: Consolas, 'Courier New', monospace;
}

.ai-analysis__markdown :deep(strong) { color: #eaf3ff; }

.format-badge,
.version-badge {
  display: inline-block;
  border-radius: 999px;
  font-size: .78rem;
  font-weight: 500;
}

.format-badge { padding: 2px 10px; letter-spacing: .02em; }
.version-badge { padding: 2px 9px; white-space: nowrap; }

.format-badge--arff {
  background: rgba(91,166,255,.12);
  color: #9ad6ff;
}

.format-badge--csv {
  background: rgba(83,229,200,.1);
  color: #6fe8d0;
}

.format-badge--json {
  background: rgba(154,128,255,.12);
  color: #b8a8ff;
}

.text-muted { color: rgba(220,234,255,.45); }

.text-active { color: #53e5c8; }

.upload-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg,#5ba6ff,#407acc);
  color: #fff;
  font-size: .9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .2s;
  flex-shrink: 0;
}

.upload-btn:hover { opacity: .9; }

.dataset-ops {
  display: flex;
  gap: 6px;
  justify-content: center;
  align-items: center;
}

.dataset-ops .el-button {
  border-radius: 999px;
  border: 1px solid rgba(91,166,255,.35);
  background: rgba(91,166,255,.14);
  color: #9ad6ff;
  font-size: .78rem;
}

.dataset-ops .el-button + .el-button { margin-left: 0; }

.dataset-ops .el-button:hover {
  background: rgba(91,166,255,.26);
  border-color: rgba(91,166,255,.55);
  color: #fff;
}

.version-badge--off {
  background: rgba(220,234,255,.08);
  color: rgba(220,234,255,.5);
}

.iteration-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: .8rem;
  color: rgba(220,234,255,.82);
  white-space: nowrap;
}

.iteration-tag__flag {
  padding: 1px 6px;
  border-radius: 999px;
  font-size: .7rem;
}

.version-badge--on,
.iteration-tag__flag--compatible {
  background: rgba(83,229,200,.12);
  color: #53e5c8;
}

.iteration-tag__flag--breaking {
  background: rgba(255,176,122,.14);
  color: #ffb07a;
}

.revision-history__title {
  font-size: .85rem;
  color: rgba(220,234,255,.72);
  margin-bottom: 6px;
}

.revision-history {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(220,234,255,.1);
  border-radius: 8px;
  background: rgba(255,255,255,.02);
  padding: 10px 12px;
}

.revision-history .version-tip { margin: 0; }

.revision-history__list {
  list-style: none;
  margin: 0;
  padding: 0 4px 0 0;
  overflow-y: auto;
  min-height: 0;
}

.revision-history__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: .78rem;
  color: rgba(220,234,255,.72);
  border-bottom: 1px dashed rgba(220,234,255,.06);
}

.revision-history__time,
.revision-history__mode {
  flex: 0 0 auto;
  color: rgba(220,234,255,.55);
}

.revision-history__summary {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-form {
  display: grid;
  gap: 14px;
}

.upload-form__row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.upload-form__label {
  font-size: .85rem;
  color: rgba(220,234,255,.7);
}

.upload-form__label .required {
  color: #ff7b72;
  margin-left: 2px;
}

.upload-form__input {
  padding: 9px 12px;
  border-radius: 8px;
  border: 1px solid rgba(125,201,255,.2);
  background: rgba(8,17,31,.7);
  color: #e8f1ff;
  font-size: .88rem;
  outline: none;
}

.upload-form__input:focus { border-color: rgba(91,166,255,.5); }

.upload-form__hint {
  margin: -4px 0 0;
  font-size: .76rem;
  color: rgba(220,234,255,.48);
}

.upload-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(125,201,255,.2);
  border-radius: 8px;
  background: rgba(8,17,31,.7);
}

.upload-picker__input { display: none; }

.upload-picker__name {
  min-width: 0;
  font-size: .82rem;
  color: rgba(220,234,255,.85);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-picker__name.is-empty { color: rgba(220,234,255,.4); }

.upload-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 8px;
  border: 1px dashed rgba(91,166,255,.35);
  background: rgba(91,166,255,.07);
  color: #9ad6ff;
  cursor: pointer;
  transition: all .2s;
  flex-shrink: 0;
}

.upload-icon-btn svg {
  width: 20px;
  height: 20px;
}

.upload-icon-btn:hover {
  background: rgba(91,166,255,.18);
  border-color: rgba(91,166,255,.55);
}

.version-tip {
  margin: 12px 0 0;
  font-size: .8rem;
  color: rgba(220,234,255,.5);
  line-height: 1.6;
}

.version-dialog-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}
</style>

<style>
.dataset-center :is(.el-table, .el-table__inner-wrapper, .el-table__body-wrapper, .el-table__header-wrapper) {
  background-color: transparent !important;
}

.dataset-center .el-table tr { background-color: var(--app-table-row-bg) !important; }

.dataset-center .el-table__body tr.el-table__row--striped {
  background-color: var(--app-table-row-striped-bg) !important;
}

.dataset-center .el-table th.el-table__cell {
  background-color: var(--app-table-header-bg) !important;
  color: rgba(155,195,240,.85) !important;
  font-weight: 600;
  border-bottom: 1px solid rgba(125,201,255,.08) !important;
}

.dataset-center .el-table td.el-table__cell {
  background-color: var(--app-table-row-bg) !important;
  color: rgba(175,198,230,.85) !important;
  border-bottom: 1px solid rgba(125,201,255,.04) !important;
}

.dataset-center .el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background-color: var(--app-table-row-striped-bg) !important;
}

.dataset-center .el-table__body tr:hover > td.el-table__cell {
  background-color: var(--app-table-row-hover-bg) !important;
}

.dataset-center .el-table__empty-text { color: rgba(180,200,235,.3) !important; }

.ai-analysis-dialog {
  display: flex;
  flex-direction: column;
  max-height: 86vh;
  margin-bottom: 0 !important;
  overflow: hidden;
}

.ai-analysis-dialog .el-dialog__header,
.ai-analysis-dialog .el-dialog__footer {
  flex: 0 0 auto;
}

.ai-analysis-dialog .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.version-dialog {
  --version-pane-max-h: calc((88vh - 220px) / 2);
  display: flex;
  flex-direction: column;
  max-width: 96vw;
  max-height: 88vh;
  overflow: hidden;
}

.version-dialog .el-dialog__header { flex: 0 0 auto; }

.version-dialog .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
}

.version-dialog .revision-history { max-height: var(--version-pane-max-h); }
</style>
