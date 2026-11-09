<script setup lang="ts">
/** 贝叶斯网络模型中心：训练版本、指标、对比、AI 评价、导出与删除。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { getAlgorithms, getDatasets } from '@/api/trainingApi';
import {
  deleteModelVersion,
  exportModelPackage,
  exportModelPackages,
  getModelVersionPage,
  modelPackageDownloadUrl,
} from '@/api/modelVersionApi';
import type { BackendModelVersion } from '@/api/modelVersionApi';
import {
  getModelEvaluation,
  streamModelEvaluation,
  type ModelEvaluationResponse,
} from '@/api/modelEvaluationApi';
import type { EvaluationMetrics } from '@/types/security';
import { keepScroll } from '@/utils/scrollAnchor';

const models = ref<BackendModelVersion[]>([]);
const algorithms = ref<Array<{ id: number; display_name: string }>>([]);
const loading = ref(true);
const error = ref('');
const page = ref(1);
const pageSize = 10;
const total = ref(0);
const exportingId = ref<number | null>(null);
const batchExporting = ref(false);
const deletingId = ref<number | null>(null);
const batchDeleting = ref(false);
const operationBusy = computed(
  () => exportingId.value !== null || batchExporting.value || deletingId.value !== null || batchDeleting.value,
);

const selectedDataset = ref('all');
interface DatasetOption { id: number; name: string; version: number; }
const allDatasets = ref<DatasetOption[]>([]);

const algoName = (id: string | number) =>
  algorithms.value.find((item) => String(item.id) === String(id))?.display_name ?? String(id);

const statusText = (status: string) =>
  status === 'TRAINING' ? '训练中' : status === 'FAILED' ? '训练失败' : '已完成';
const isReady = (model: BackendModelVersion) => model.status !== 'TRAINING' && model.status !== 'FAILED';

const datasetOptions = computed(() => allDatasets.value.map((dataset) => ({
  id: String(dataset.id),
  name: `${dataset.name}（v${dataset.version}）`,
})));

const queryParams = (): Parameters<typeof getModelVersionPage>[0] => ({
  dataset_id: selectedDataset.value === 'all' ? undefined : selectedDataset.value,
  page_size: pageSize,
});

let loadSeq = 0;
const loadModels = async (targetPage: number = page.value) => {
  const seq = ++loadSeq;
  loading.value = true;
  error.value = '';
  try {
    const data = await getModelVersionPage({ ...queryParams(), page: targetPage });
    if (seq !== loadSeq) return;
    if (!data.items.length && data.total > 0 && targetPage > 1) {
      await loadModels(Math.max(1, Math.ceil(data.total / pageSize)));
      return;
    }
    models.value = data.items;
    total.value = data.total;
    page.value = data.page;
    for (const item of data.items) if (batchSelectionCache.has(item.id)) batchSelectionCache.set(item.id, item);
  } catch (err) {
    if (seq !== loadSeq) return;
    error.value = err instanceof Error ? err.message : '模型数据加载失败';
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
};

const listRef = ref<HTMLElement | null>(null);
const changePage = (target: number) => keepScroll(() => loadModels(target), listRef.value);
const ready = ref(false);

interface ConfirmOptions {
  title: string;
  message: string;
  detail?: string;
  confirmText?: string;
  cancelText?: string;
  tone?: 'primary' | 'danger';
  icon?: string;
}

interface ConfirmDialogState extends ConfirmOptions {
  tone: 'primary' | 'danger';
  confirmText: string;
  cancelText: string;
}

const confirmDialog = ref<ConfirmDialogState | null>(null);
const confirmPrimaryRef = ref<HTMLButtonElement | null>(null);
let confirmResolver: ((confirmed: boolean) => void) | null = null;

const askConfirm = (options: ConfirmOptions): Promise<boolean> => {
  confirmResolver?.(false);
  confirmDialog.value = {
    ...options,
    tone: options.tone ?? 'primary',
    confirmText: options.confirmText ?? '确认',
    cancelText: options.cancelText ?? '取消',
  };
  return new Promise((resolve) => {
    confirmResolver = resolve;
  });
};

const settleConfirm = (confirmed: boolean) => {
  const resolve = confirmResolver;
  confirmResolver = null;
  confirmDialog.value = null;
  resolve?.(confirmed);
};

watch(confirmDialog, (dialog) => {
  if (!dialog) return;
  void nextTick(() => confirmPrimaryRef.value?.focus());
});

const handleExport = async (model: BackendModelVersion) => {
  if (operationBusy.value) return;
  const confirmed = await askConfirm({
    title: '确认导出模型？',
    message: `确定导出模型 #${model.id} 的模型包吗？`,
    detail: '确认后将生成 ZIP 模型包并自动下载。',
    confirmText: '确认导出',
    icon: '↓',
  });
  if (!confirmed || operationBusy.value) return;
  exportingId.value = model.id;
  try {
    await exportModelPackage(model.id);
    const link = document.createElement('a');
    link.href = modelPackageDownloadUrl(model.id);
    link.download = `model_${model.id}_closed-loop-v1.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    ElMessage.success(`模型 ${model.id} 已导出`);
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '导出失败');
  } finally {
    exportingId.value = null;
  }
};
const handleDelete = async (model: BackendModelVersion) => {
  if (operationBusy.value) return;
  const confirmed = await askConfirm({
    title: '确认删除模型？',
    message: `确定删除模型 #${model.id} 吗？`,
    detail: '删除后不可恢复，请确认该模型不再需要。',
    confirmText: '确认删除',
    tone: 'danger',
    icon: '!',
  });
  if (!confirmed || operationBusy.value) return;
  deletingId.value = model.id;
  try {
    await deleteModelVersion(model.id);
    ElMessage.success(`模型 ${model.id} 已删除`);
    batchSelectedIds.value = batchSelectedIds.value.filter((id) => id !== model.id);
    batchSelectionCache.delete(model.id);
    batchModels.value = batchModels.value.filter((item) => item.id !== model.id);
    await loadModels();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '删除失败');
  } finally {
    deletingId.value = null;
  }
};

const MAX_COMPARE_MODELS = 5;
const compareVisible = ref(false);
const closeCompare = () => { compareVisible.value = false; };

const batchExportMode = ref(false);
const batchModels = ref<BackendModelVersion[]>([]);
const batchSelectedIds = ref<number[]>([]);
const batchSelectionCache = new Map<number, BackendModelVersion>();
const batchLoading = ref(false);
let batchLoadSeq = 0;

const batchExportableModels = computed(() => batchModels.value.filter(isReady));
const batchSelectableCount = computed(() => batchExportableModels.value.length);
const batchSelectedCount = computed(() => batchSelectedIds.value.length);
const allBatchExportableSelected = computed(
  () => batchSelectableCount.value > 0 && batchSelectedCount.value === batchSelectableCount.value,
);
const isCardSelectable = (model: BackendModelVersion) =>
  batchExportMode.value && isReady(model);
const isCardPicked = (model: BackendModelVersion) =>
  batchExportMode.value && batchSelectedIds.value.includes(model.id);
const compareList = computed(() => batchSelectedIds.value
  .map((id) => batchSelectionCache.get(id))
  .filter((item): item is BackendModelVersion => Boolean(item)));

const handleCompareSelected = () => {
  if (batchSelectedIds.value.length < 2) {
    ElMessage.warning('请至少选择 2 个模型进行对比');
    return;
  }
  if (batchSelectedIds.value.length > MAX_COMPARE_MODELS) {
    ElMessage.warning(`最多选择 ${MAX_COMPARE_MODELS} 个模型进行对比`);
    return;
  }
  if (compareList.value.length !== batchSelectedIds.value.length) {
    ElMessage.warning('模型数据仍在载入，请稍后再试');
    return;
  }
  compareVisible.value = true;
};

const loadBatchModels = async () => {
  const seq = ++batchLoadSeq;
  batchLoading.value = true;
  try {
    const rows: BackendModelVersion[] = [];
    let targetPage = 1;
    while (true) {
      const data = await getModelVersionPage({ ...queryParams(), page: targetPage, page_size: 200 });
      rows.push(...data.items);
      if (!data.items.length || rows.length >= data.total) break;
      targetPage += 1;
    }
    if (seq !== batchLoadSeq || !batchExportMode.value) return;
    batchModels.value = rows;
    const readyIds = new Set(rows.filter(isReady).map((item) => item.id));
    batchSelectedIds.value = batchSelectedIds.value.filter((id) => readyIds.has(id));
    for (const model of rows) {
      if (batchSelectedIds.value.includes(model.id)) batchSelectionCache.set(model.id, model);
    }
  } catch (err) {
    if (seq !== batchLoadSeq) return;
    batchModels.value = [];
    batchSelectedIds.value = [];
    batchSelectionCache.clear();
    ElMessage.error(err instanceof Error ? err.message : '可选模型加载失败');
  } finally {
    if (seq === batchLoadSeq) batchLoading.value = false;
  }
};

const startBatchExport = () => {
  if (batchExportMode.value) return;
  batchExportMode.value = true;
  batchModels.value = [];
  batchSelectedIds.value = [];
  batchSelectionCache.clear();
  void loadBatchModels();
};

const cancelBatchExport = () => {
  batchLoadSeq += 1;
  batchExportMode.value = false;
  batchLoading.value = false;
  batchModels.value = [];
  batchSelectedIds.value = [];
  batchSelectionCache.clear();
  compareVisible.value = false;
};

const toggleBatchExport = (model: BackendModelVersion) => {
  if (!isReady(model)) return;
  const index = batchSelectedIds.value.indexOf(model.id);
  if (index >= 0) {
    batchSelectedIds.value.splice(index, 1);
    batchSelectionCache.delete(model.id);
  } else {
    batchSelectedIds.value.push(model.id);
    batchSelectionCache.set(model.id, model);
  }
};

const selectAllForBatchExport = () => {
  if (batchLoading.value) return;
  batchSelectedIds.value = batchExportableModels.value.map((item) => item.id);
  for (const model of batchExportableModels.value) batchSelectionCache.set(model.id, model);
};

const invertBatchExportSelection = () => {
  if (batchLoading.value) return;
  const selected = new Set(batchSelectedIds.value);
  batchSelectedIds.value = batchExportableModels.value
    .filter((item) => !selected.has(item.id))
    .map((item) => item.id);
  batchSelectionCache.clear();
  for (const model of batchExportableModels.value) {
    if (batchSelectedIds.value.includes(model.id)) batchSelectionCache.set(model.id, model);
  }
};

const handleCardClick = (model: BackendModelVersion) => {
  if (batchExportMode.value) toggleBatchExport(model);
};

const handleBatchExport = async () => {
  if (operationBusy.value) return;
  const modelIds = [...batchSelectedIds.value];
  if (!modelIds.length) {
    ElMessage.warning('请先选择要导出的模型');
    return;
  }
  const confirmed = await askConfirm({
    title: '确认批量导出？',
    message: `确定导出已选的 ${modelIds.length} 个模型包吗？`,
    detail: '确认后将生成一个 ZIP 压缩包并自动下载。',
    confirmText: `导出 ${modelIds.length} 个`,
    icon: '↓',
  });
  if (!confirmed || operationBusy.value) return;
  batchExporting.value = true;
  try {
    const blob = await exportModelPackages(modelIds);
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '');
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `model_packages_${stamp}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    ElMessage.success(`已导出 ${modelIds.length} 个模型包`);
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '批量导出失败');
  } finally {
    batchExporting.value = false;
  }
};

const handleBatchDelete = async () => {
  if (operationBusy.value || batchLoading.value) return;
  const modelIds = [...batchSelectedIds.value];
  if (!modelIds.length) {
    ElMessage.warning('请先选择要删除的模型');
    return;
  }
  const confirmed = await askConfirm({
    title: '确认批量删除？',
    message: `确定删除已选的 ${modelIds.length} 个模型吗？`,
    detail: '删除后不可恢复，请确认这些模型不再需要。',
    confirmText: `删除 ${modelIds.length} 个`,
    tone: 'danger',
    icon: '!',
  });
  if (!confirmed || operationBusy.value) return;

  batchDeleting.value = true;
  const deletedIds = new Set<number>();
  const failures: string[] = [];
  try {
    for (const modelId of modelIds) {
      try {
        await deleteModelVersion(modelId);
        deletedIds.add(modelId);
      } catch (err) {
        failures.push(`#${modelId}：${err instanceof Error ? err.message : '删除失败'}`);
      }
    }

    if (deletedIds.size) {
      batchSelectedIds.value = batchSelectedIds.value.filter((id) => !deletedIds.has(id));
      for (const modelId of deletedIds) batchSelectionCache.delete(modelId);
      batchModels.value = batchModels.value.filter((item) => !deletedIds.has(item.id));
      await loadModels();
    }

    if (failures.length) {
      const prefix = deletedIds.size ? `已删除 ${deletedIds.size} 个，` : '';
      ElMessage.error(`${prefix}${failures.length} 个删除失败：${failures[0]}`);
    } else {
      ElMessage.success(`已删除 ${modelIds.length} 个模型`);
    }
  } finally {
    batchDeleting.value = false;
  }
};

watch(selectedDataset, () => {
  if (ready.value) void loadModels(1);
  if (!batchExportMode.value) return;
  batchSelectedIds.value = [];
  batchSelectionCache.clear();
  void loadBatchModels();
});

interface MetricRow { label: string; key: keyof EvaluationMetrics; better: 'max' | 'min'; }
const allMetricRows: MetricRow[] = [
  { label: 'Accuracy', key: 'accuracy', better: 'max' },
  { label: 'Recall', key: 'recall', better: 'max' },
  { label: 'Precision', key: 'precision', better: 'max' },
  { label: 'Specificity', key: 'specificity', better: 'max' },
  { label: 'F1', key: 'f1', better: 'max' },
  { label: 'G-mean', key: 'g_mean', better: 'max' },
  { label: 'Risk Recall', key: 'risk_recall', better: 'max' },
  { label: 'Risk F1', key: 'risk_f1', better: 'max' },
  { label: 'CV Mean', key: 'cv_mean', better: 'max' },
  { label: 'CV Std', key: 'cv_std', better: 'min' },
];
const bestValueOf = (row: MetricRow): number | null => {
  if (compareList.value.length < 2) return null;
  const values = compareList.value.map((item) => Number(item.evaluation_metrics?.[row.key])).filter(Number.isFinite);
  if (!values.length) return null;
  return row.better === 'min' ? Math.min(...values) : Math.max(...values);
};
const isBest = (model: BackendModelVersion, row: MetricRow) => {
  const best = bestValueOf(row);
  const value = Number(model.evaluation_metrics?.[row.key]);
  return best !== null && Number.isFinite(value) && value === best;
};
const metricDelta = (model: BackendModelVersion, row: MetricRow) => {
  const best = bestValueOf(row);
  const value = Number(model.evaluation_metrics?.[row.key]);
  if (best === null || !Number.isFinite(value) || value === best) return null;
  const diff = (value - best) * 100;
  return Math.abs(diff) < 0.05 ? null : `${diff > 0 ? '+' : '-'}${Math.abs(diff).toFixed(1)}`;
};
const metricValue = (model: BackendModelVersion, key: keyof EvaluationMetrics) => {
  const value = Number(model.evaluation_metrics?.[key]);
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';
};

const FEATURE_PROFILE_LIMIT = 8;
const evaluationTarget = ref<BackendModelVersion | null>(null);
const evaluationLoading = ref(false);
const evaluation = ref<ModelEvaluationResponse | null>(null);
const evaluationMarkdown = ref('');
const evaluationReasoning = ref('');
const evaluationStatus = ref('');
const evaluationError = ref('');
let evaluationAbort: AbortController | null = null;
let evaluationRequestId = 0;
const isCurrentEvaluation = (requestId: number) => requestId === evaluationRequestId;
const evaluationBodyRef = ref<HTMLElement | null>(null);
const evaluationReasoningRef = ref<HTMLElement | null>(null);
const stickEvaluationToBottom = () => {
  if (!evaluationLoading.value) return;
  void nextTick(() => {
    for (const element of [evaluationBodyRef.value, evaluationReasoningRef.value]) if (element) element.scrollTop = element.scrollHeight;
  });
};
watch([evaluationReasoning, evaluationMarkdown], stickEvaluationToBottom);
const safeEvaluationHtml = computed(() => evaluationMarkdown.value
  ? DOMPurify.sanitize(marked.parse(evaluationMarkdown.value, { async: false }) as string)
  : '');

const loadEvaluation = async () => {
  const target = evaluationTarget.value;
  if (!target || evaluationLoading.value) return;
  const requestId = ++evaluationRequestId;
  evaluationStatus.value = '正在读取模型属性...';
  try {
    const response = await getModelEvaluation(target.id);
    if (!isCurrentEvaluation(requestId)) return;
    evaluation.value = response;
    evaluationMarkdown.value = response.evaluation.markdown || '';
    evaluationStatus.value = '';
    evaluationError.value = '';
  } catch (err) {
    if (!isCurrentEvaluation(requestId)) return;
    evaluationError.value = err instanceof Error ? err.message : '模型评价读取失败';
    evaluationStatus.value = '';
  }
};
const openModelEvaluation = (model: BackendModelVersion) => {
  evaluationRequestId += 1;
  evaluationAbort?.abort(); evaluationAbort = null;
  evaluationTarget.value = model;
  evaluation.value = null; evaluationMarkdown.value = ''; evaluationReasoning.value = '';
  evaluationStatus.value = ''; evaluationError.value = ''; evaluationLoading.value = false;
  void loadEvaluation();
};
const closeModelEvaluation = () => {
  evaluationRequestId += 1;
  evaluationAbort?.abort(); evaluationAbort = null;
  evaluationLoading.value = false;
  evaluationTarget.value = null;
};
const generateModelEvaluation = async (regenerate = false) => {
  const target = evaluationTarget.value;
  if (!target || evaluationLoading.value) return;
  const requestId = ++evaluationRequestId;
  evaluationAbort?.abort();
  const controller = new AbortController();
  evaluationAbort = controller;
  evaluationLoading.value = true;
  evaluationError.value = ''; evaluationReasoning.value = '';
  if (regenerate) evaluationMarkdown.value = '';
  evaluationStatus.value = regenerate ? '正在重新生成模型评价...' : '正在生成模型评价...';
  try {
    await streamModelEvaluation(target.id, regenerate, {
      onStart: (data) => { if (isCurrentEvaluation(requestId)) evaluationStatus.value = String(data.status || '评价生成中'); },
      onReasoning: (content) => { if (isCurrentEvaluation(requestId)) evaluationReasoning.value += content; },
      onDelta: (content) => {
        if (!isCurrentEvaluation(requestId)) return;
        if (evaluationReasoning.value) evaluationReasoning.value = '';
        evaluationMarkdown.value += content;
      },
      onError: (data) => {
        if (!isCurrentEvaluation(requestId)) return;
        evaluationError.value = String(data.message || 'AI 服务不可用');
        evaluationMarkdown.value = ''; evaluationReasoning.value = '';
      },
      onDone: () => {
        if (!isCurrentEvaluation(requestId)) return;
        evaluationStatus.value = ''; stickEvaluationToBottom();
      },
    }, controller.signal);
    const nextEvaluation = await getModelEvaluation(target.id);
    if (isCurrentEvaluation(requestId)) evaluation.value = nextEvaluation;
  } catch (err) {
    if (!isCurrentEvaluation(requestId) || (err as Error)?.name === 'AbortError') return;
    evaluationError.value = err instanceof Error ? err.message : '模型评价生成失败';
    evaluationStatus.value = ''; evaluationReasoning.value = '';
  } finally {
    if (isCurrentEvaluation(requestId)) {
      evaluationLoading.value = false; evaluationAbort = null;
    }
  }
};
const exportModelEvaluation = async () => {
  const target = evaluationTarget.value;
  if (!target || !evaluationMarkdown.value) return;
  const confirmed = await askConfirm({
    title: '确认导出评价？',
    message: `确定导出模型 #${target.id} 的 AI 评价吗？`,
    detail: '确认后将下载 Markdown 格式的评价文件。',
    confirmText: '确认导出',
    icon: '↓',
  });
  if (!confirmed) return;
  const content = `# 模型 #${target.id} 评价\n\n${evaluationMarkdown.value}\n`;
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `model-${target.id}-evaluation.md`; anchor.click();
  URL.revokeObjectURL(url);
  ElMessage.success('模型评价已导出');
};

watch([evaluationTarget, compareVisible, confirmDialog], ([target, comparing, confirming]) => {
  document.body.style.overflow = target || comparing || confirming ? 'hidden' : '';
});
const handleEvaluationKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Escape') return;
  if (confirmDialog.value) settleConfirm(false);
  else if (evaluationTarget.value) closeModelEvaluation();
  else if (compareVisible.value) closeCompare();
};
window.addEventListener('keydown', handleEvaluationKeydown);
onBeforeUnmount(() => {
  evaluationRequestId += 1;
  evaluationAbort?.abort(); evaluationAbort = null;
  settleConfirm(false);
  window.removeEventListener('keydown', handleEvaluationKeydown);
  document.body.style.overflow = '';
});

onMounted(async () => {
  try {
    const rows = await getAlgorithms();
    algorithms.value = rows.map((item) => ({ id: item.id, display_name: item.display_name || item.code }));
    allDatasets.value = (await getDatasets()).map(({ id, name, version }) => ({ id, name, version }));
    await loadModels(1);
    ready.value = true;
  } catch (err) {
    error.value = err instanceof Error ? err.message : '初始化贝叶斯网络模型中心失败';
    loading.value = false;
  }
});
</script>

<template>
  <div class="model-center">
    <Teleport to="body">
      <div
        v-if="confirmDialog"
        class="confirm-modal"
        role="presentation"
        @click.self="settleConfirm(false)"
      >
        <div
          class="confirm-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
          aria-describedby="confirm-dialog-message"
        >
          <div
            class="confirm-dialog__icon"
            :class="`confirm-dialog__icon--${confirmDialog.tone}`"
            aria-hidden="true"
          >{{ confirmDialog.icon || (confirmDialog.tone === 'danger' ? '!' : '?') }}</div>
          <div class="confirm-dialog__content">
            <h3 id="confirm-dialog-title">{{ confirmDialog.title }}</h3>
            <p id="confirm-dialog-message">{{ confirmDialog.message }}</p>
            <p v-if="confirmDialog.detail" class="confirm-dialog__detail">{{ confirmDialog.detail }}</p>
          </div>
          <div class="confirm-dialog__actions">
            <button class="op-btn op-btn--quiet" type="button" @click="settleConfirm(false)">
              {{ confirmDialog.cancelText }}
            </button>
            <button
              ref="confirmPrimaryRef"
              class="op-btn"
              :class="{ 'op-btn--danger': confirmDialog.tone === 'danger' }"
              type="button"
              @click="settleConfirm(true)"
            >{{ confirmDialog.confirmText }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <div class="model-center__toolbar">
      <div class="model-center__filters">
        <select v-model="selectedDataset" class="model-filter-select">
          <option value="all">全部数据集</option>
          <option v-for="d in datasetOptions" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </div>
      <div class="model-center__toolbar-right">
        <span class="model-center__count">
          共 <strong>{{ total }}</strong> 个模型版本
          <template v-if="batchExportMode">
            · 已选 <strong>{{ batchSelectedCount }}</strong>
            <template v-if="batchLoading"> · 正在载入可选模型...</template>
            <template v-else> / 可选 <strong>{{ batchSelectableCount }}</strong></template>
          </template>
        </span>
        <div class="model-center__actions">
          <template v-if="batchExportMode">
            <button
              class="tool-btn"
              type="button"
              :disabled="batchLoading || operationBusy"
              @click="selectAllForBatchExport"
            >全选</button>
            <button
              class="tool-btn"
              type="button"
              :disabled="batchLoading || operationBusy"
              @click="invertBatchExportSelection"
            >反选</button>
            <button
              class="tool-btn tool-btn--primary"
              type="button"
              :disabled="batchLoading || operationBusy || batchSelectedCount < 2"
              @click="handleCompareSelected"
            >
              对比已选（{{ batchSelectedCount }}）
            </button>
            <button
              class="tool-btn"
              type="button"
              :disabled="batchLoading || batchSelectedCount === 0 || operationBusy"
              @click="handleBatchExport"
            >
              {{ batchExporting ? '导出中…' : (allBatchExportableSelected ? '全部导出' : '导出已选') }}（{{ batchSelectedCount }}）
            </button>
            <button
              class="tool-btn tool-btn--danger"
              type="button"
              :disabled="batchLoading || batchSelectedCount === 0 || operationBusy"
              @click="handleBatchDelete"
            >
              {{ batchDeleting ? '删除中…' : `删除已选（${batchSelectedCount}）` }}
            </button>
            <button
              class="tool-btn"
              type="button"
              :disabled="batchDeleting"
              @click="cancelBatchExport"
            >取消多选</button>
          </template>
          <button
            v-else
            class="tool-btn"
            type="button"
            :disabled="total === 0 || operationBusy"
            @click="startBatchExport"
          >
            多选
          </button>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="evaluationTarget"
        class="model-evaluation-modal"
        @click.self="closeModelEvaluation"
      >
        <div class="model-evaluation-modal__card">
          <div class="model-evaluation-modal__head">
            <div class="model-evaluation-modal__title">
              <h3>模型 #{{ evaluationTarget.id }} 评价</h3>
            </div>
            <div class="model-evaluation-modal__head-actions">
              <button
                class="op-btn op-btn--quiet"
                type="button"
                :disabled="!evaluationMarkdown"
                @click="exportModelEvaluation"
              >
                导出
              </button>
              <button
                class="op-btn"
                :disabled="evaluationLoading"
                @click="generateModelEvaluation(Boolean(evaluationMarkdown))"
              >
                {{ evaluationMarkdown ? '重新生成' : '生成评价' }}
              </button>
              <button
                class="model-evaluation-modal__close"
                type="button"
                aria-label="关闭"
                title="关闭"
                @click="closeModelEvaluation"
              >✕</button>
            </div>
          </div>

          <div ref="evaluationBodyRef" class="model-evaluation-modal__body">
            <div v-if="evaluationError" class="model-evaluation-modal__notice model-evaluation-modal__notice--error">
              {{ evaluationError }}
            </div>
            <div v-if="evaluationStatus" class="model-evaluation-modal__status">{{ evaluationStatus }}</div>
            <div v-if="evaluationLoading" class="model-evaluation-loading">
              <span class="model-evaluation-loading__dot"></span>
              <span>AI 正在生成评价，请稍候…</span>
            </div>

            <div v-if="evaluationReasoning" class="model-evaluation-reasoning">
              <div class="model-evaluation-reasoning__label">模型推理中</div>
              <div ref="evaluationReasoningRef" class="model-evaluation-reasoning__text">{{ evaluationReasoning }}</div>
            </div>

            <div v-if="evaluation?.model_attributes" class="model-evaluation-facts">
              <div class="model-evaluation-fact">
                <span>算法</span>
                <strong>{{ evaluation.model_attributes.algorithm?.name || evaluation.model_attributes.algorithm?.code || '—' }}</strong>
              </div>
              <div class="model-evaluation-fact">
                <span>数据集</span>
                <strong>{{ evaluation.model_attributes.dataset?.name || '—' }}</strong>
              </div>
              <div class="model-evaluation-fact">
                <span>模型版本</span>
                <strong>#{{ evaluation.model_attributes.model_version_id || evaluationTarget?.id }}</strong>
              </div>
              <div class="model-evaluation-fact">
                <span>评价范围</span>
                <strong>模型版本本身</strong>
              </div>
            </div>

            <div v-if="evaluation?.model_attributes?.feature_profile?.length" class="model-evaluation-fields">
              <span class="model-evaluation-fields__label">输入特征</span>
              <span
                v-for="field in evaluation.model_attributes.feature_profile.slice(0, FEATURE_PROFILE_LIMIT)"
                :key="field.name"
                class="model-evaluation-field"
              >
                {{ field.display_name || field.name }}
              </span>
            </div>

            <div v-if="safeEvaluationHtml" class="model-evaluation-markdown" v-html="safeEvaluationHtml"></div>
            <div v-else-if="!evaluationLoading" class="model-evaluation-empty">点击“生成评价”调用 AI；评价结果会保存到该模型版本。</div>
          </div>

          <div class="model-evaluation-modal__foot">
            <button class="op-btn op-btn--quiet" @click="closeModelEvaluation">关闭</button>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="compareVisible" class="compare-modal" @click.self="closeCompare">
        <div class="compare-modal__card">
          <div class="compare-modal__head">
            <div>
              <h3>模型版本对比</h3>
            </div>
            <div class="compare-modal__head-actions">
              <button
                class="compare-modal__close"
                type="button"
                aria-label="关闭"
                title="关闭"
                @click="closeCompare"
              >✕</button>
            </div>
          </div>

          <div class="compare-modal__body">
            <div class="compare-table-wrap">
              <table class="compare-table">
                <thead>
                  <tr>
                    <th>编号</th>
                    <th v-for="m in compareList" :key="m.id">#{{ m.id }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>算法</td>
                    <td v-for="m in compareList" :key="'algo-' + m.id">
                      {{ m.algorithm_name || algoName(String(m.algorithm_id)) }}
                    </td>
                  </tr>
                  <tr>
                    <td>数据集</td>
                    <td v-for="m in compareList" :key="'ds-' + m.id">
                      {{ m.dataset_name || '未命名数据集' }} v{{ m.dataset_version || '—' }}
                    </td>
                  </tr>
                  <tr>
                    <td>状态</td>
                    <td v-for="m in compareList" :key="'st-' + m.id">{{ statusText(m.status) }}</td>
                  </tr>
                  <tr v-for="row in allMetricRows" :key="row.key">
                    <td>{{ row.label }}</td>
                    <td
                      v-for="m in compareList"
                      :key="'m-' + row.key + '-' + m.id"
                      :class="{ 'compare-best': isBest(m, row) }"
                    >
                      <span>{{ metricValue(m, row.key) }}</span>
                      <span v-if="metricDelta(m, row)" class="compare-cell__delta">{{ metricDelta(m, row) }}</span>
                    </td>
                  </tr>
                  <tr>
                    <td>训练时间</td>
                    <td v-for="m in compareList" :key="'t-' + m.id">{{ m.trained_at }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="compare-modal__foot">
            <button class="op-btn op-btn--quiet" type="button" @click="closeCompare">关闭</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 首屏加载：列表还是空的才用整块状态卡，翻页走列表内的局部遮罩 -->
    <section v-if="loading && !models.length" class="state-card">
      <div class="loader"></div>
      <p>正在加载模型数据...</p>
    </section>

    <section v-else-if="error" class="state-card state-card--error">
      <p>{{ error }}</p>
      <button class="ghost-button" @click="loadModels()">重试</button>
    </section>

    <section v-else-if="!models.length" class="state-card">
      <p>当前筛选范围内暂无模型版本</p>
    </section>

    <template v-else>
    <div ref="listRef" class="model-center__list">
      <div v-if="loading" class="pane-loading"><div class="loader"></div></div>
      <div
        v-for="model in models"
        :key="model.id"
        class="model-card card"
        :class="{ 'is-selectable': isCardSelectable(model), 'is-selected': isCardPicked(model) }"
        @click="handleCardClick(model)"
      >
        <div class="model-card__header">
          <div class="model-card__titles">
            <h3 class="model-card__id">模型 #{{ model.id }}</h3>
            <span
              v-if="batchExportMode && isReady(model)"
              class="model-card__check"
              :class="{ 'is-on': isCardPicked(model) }"
              aria-hidden="true"
            >✓</span>
          </div>
          <div class="model-card__header-right">
            <button
              v-if="isReady(model)"
              class="card-chip-btn"
              @click.stop="openModelEvaluation(model)"
            >AI 评价</button>
            <button
              v-if="isReady(model)"
              class="card-chip-btn card-chip-btn--export"
              :disabled="operationBusy"
              @click.stop="handleExport(model)"
            >{{ exportingId === model.id ? '导出中…' : '导出' }}</button>
            <button
              v-if="isReady(model) || model.status === 'FAILED'"
              class="card-chip-btn card-chip-btn--danger"
              :disabled="operationBusy"
              @click.stop="handleDelete(model)"
            >{{ deletingId === model.id ? '删除中…' : '删除' }}</button>
          </div>
        </div>

        <div class="model-card__meta">
          <div class="model-card__meta-item">
            <span class="model-card__meta-label">数据集</span>
            <span
              class="model-card__meta-value"
              :title="`${model.dataset_name || '未命名数据集'} v${model.dataset_version || '—'}`"
            >
              {{ model.dataset_name || '未命名数据集' }}
              <em class="model-card__version">v{{ model.dataset_version || '—' }}</em>
            </span>
          </div>
          <div class="model-card__meta-item">
            <span class="model-card__meta-label">算法</span>
            <span
              class="model-card__meta-value"
              :title="model.algorithm_name || algoName(String(model.algorithm_id))"
            >{{ model.algorithm_name || algoName(String(model.algorithm_id)) }}</span>
          </div>
          <div class="model-card__meta-item">
            <span class="model-card__meta-label">训练时间</span>
            <span class="model-card__meta-value">{{ model.trained_at }}</span>
          </div>
        </div>

        <div class="model-card__metrics">
          <div v-for="row in allMetricRows" :key="row.key" class="model-card__metric">
            <span class="model-card__metric-value">{{ metricValue(model, row.key) }}</span>
            <span class="model-card__metric-label">{{ row.label }}</span>
          </div>
        </div>

        <div v-if="Object.keys(model.training_parameters || {}).length" class="model-card__params">
          <span
            v-for="(v, k) in model.training_parameters"
            :key="k"
            class="model-card__param"
          >
            {{ k }} = {{ v }}
          </span>
        </div>

        <div v-if="!isReady(model)" class="model-card__footer">
          <span class="model-card__failed-tip">
            {{ model.status === 'FAILED' ? '训练失败' : statusText(model.status) + '...' }}
          </span>
        </div>
      </div>
    </div>
    </template>

    <div v-if="total > 0" class="model-center__pager">
      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next"
        :page-size="pageSize"
        :total="total"
        :disabled="loading"
        background
        @current-change="changePage"
      />
    </div>
  </div>
</template>

<style scoped>
.model-center {
  position: relative;
  z-index: 1;
}

.model-center__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.model-center__filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.model-filter-select {
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(125, 201, 255, 0.2);
  background: rgba(8, 17, 31, 0.6);
  color: #e8f1ff;
  font-size: 0.88rem;
  outline: none;
}

.model-filter-select option {
  background: #0b1628;
  color: #e8f1ff;
}

.model-center__toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.model-center__count {
  font-size: 0.88rem;
  color: rgba(220, 234, 255, 0.6);
  white-space: nowrap;
}

.model-center__count strong { color: #9ad6ff; }

.model-center__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 高度与同一行的 .model-filter-select 对齐（36px，全局 border-box） */

.tool-btn {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 0 16px;
  border: 1px solid rgba(125, 201, 255, 0.24);
  border-radius: 8px;
  background: rgba(8, 17, 31, 0.6);
  color: rgba(200, 222, 255, 0.85);
  font-size: 0.88rem;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}

.tool-btn:hover:not(:disabled) {
  background: rgba(91, 166, 255, 0.16);
  color: #e8f1ff;
}

.tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tool-btn--primary {
  border-color: rgba(91, 166, 255, 0.5);
  background: rgba(91, 166, 255, 0.14);
  color: #9ad6ff;
  font-weight: 600;
}

.tool-btn--primary:hover:not(:disabled) {
  background: rgba(91, 166, 255, 0.28);
  color: #fff;
}

.tool-btn--danger {
  border-color: rgba(255, 123, 114, 0.38);
  background: rgba(255, 123, 114, 0.08);
  color: #ff9a93;
  font-weight: 600;
}

.tool-btn--danger:hover:not(:disabled) {
  border-color: rgba(255, 123, 114, 0.58);
  background: rgba(255, 123, 114, 0.18);
  color: #ffb4ae;
}

.model-center__list {
  position: relative;

  /* 翻页遮罩（.pane-loading）的定位上下文 */

  display: grid;

  gap: 18px;
}

/* 分页器（暗色）
   与推理记录 / 数据集预览保持同一套分页外观；变量挂在包裹层上。
   由 CSS 自定义属性继承进 el-pagination 内部。 */

.model-center__pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
  --el-pagination-bg-color: rgba(8, 17, 31, 0.8);
  --el-pagination-button-bg-color: rgba(12, 26, 46, 0.9);
  --el-pagination-button-disabled-bg-color: rgba(8, 17, 31, 0.45);
  --el-pagination-text-color: rgba(220, 234, 255, 0.75);
  --el-pagination-button-color: rgba(220, 234, 255, 0.75);
  --el-pagination-button-disabled-color: rgba(180, 200, 235, 0.28);
  --el-pagination-hover-color: #5ba6ff;
}

.model-center__pager :deep(.el-pagination.is-background .el-pager li),
.model-center__pager :deep(.el-pagination.is-background .btn-prev),
.model-center__pager :deep(.el-pagination.is-background .btn-next) {
  border: 1px solid rgba(125, 201, 255, 0.12);
  border-radius: 6px;
}

.model-center__pager :deep(.el-pagination.is-background .el-pager li:not(.is-active):hover),
.model-center__pager :deep(.el-pagination.is-background .btn-prev:hover),
.model-center__pager :deep(.el-pagination.is-background .btn-next:hover) {
  background-color: rgba(20, 44, 72, 0.95) !important;
  color: #9ad6ff !important;
}

.model-center__pager :deep(.el-pagination.is-background .el-pager li.is-active) {
  background-color: #3f7fd4 !important;
  color: #ffffff !important;
  border-color: transparent;
}

.model-center__pager :deep(.el-pagination.is-background .btn-prev),
.model-center__pager :deep(.el-pagination.is-background .btn-next) {
  background-color: rgba(12, 26, 46, 0.9) !important;
  color: rgba(220, 234, 255, 0.7) !important;
}

.model-center__pager :deep(.el-pagination.is-background .btn-prev:disabled),
.model-center__pager :deep(.el-pagination.is-background .btn-next:disabled) {
  background-color: rgba(8, 17, 31, 0.45) !important;
  color: rgba(180, 200, 235, 0.25) !important;
}

.model-card { padding: 20px 24px; }

/* 选择模式下整卡可点：边框 + 底色 + 左上角勾选圈三重提示，避免只靠颜色区分 */

.model-card.is-selectable { cursor: pointer; }

.model-card.is-selected {
  border-color: rgba(91, 166, 255, 0.7);
  background: linear-gradient(180deg, rgba(26, 58, 104, 0.9), rgba(10, 24, 44, 0.94));
  box-shadow: 0 0 0 1px rgba(91, 166, 255, 0.32), 0 18px 60px rgba(20, 60, 120, 0.34);
}

.model-card__check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border: 1px solid rgba(125, 201, 255, 0.42);
  border-radius: 50%;
  background: rgba(8, 17, 31, 0.7);
  color: transparent;
  font-size: 0.76rem;
  line-height: 1;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}

.model-card__check.is-on {
  border-color: #5ba6ff;
  background: #3f7fd4;
  color: #fff;
}

.model-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.model-card__titles {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.model-card__id {
  margin: 0;
  font-size: 1.05rem;
  color: #e8f1ff;
}

.model-card__meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 24px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(125, 201, 255, 0.08);
}

.model-card__meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.model-card__meta-label {
  font-size: 0.78rem;
  color: rgba(220, 234, 255, 0.55);
}

.model-card__meta-value {
  display: block;
  min-width: 0;
  overflow: hidden;
  font-size: 0.9rem;
  color: #d9e8ff;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-card__version {
  font-style: normal;
  color: rgba(154, 214, 255, 0.6);
  font-size: 0.8rem;
}

.model-card__metrics {
  display: flex;
  gap: 14px;
  margin-bottom: 14px;
}

.model-card__metric {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 8px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
}

.model-card__metric-value {
  font-size: 1.05rem;
  font-weight: 700;
  color: #9ad6ff;
  font-variant-numeric: tabular-nums;
}

.model-card__metric-label {
  font-size: 0.72rem;
  color: rgba(220, 234, 255, 0.5);
}

.model-card__params {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.model-card__param {
  padding: 3px 10px;
  border-radius: 6px;
  background: rgba(8, 17, 31, 0.7);
  border: 1px solid rgba(125, 201, 255, 0.12);
  color: rgba(154, 214, 255, 0.8);
  font-size: 0.78rem;
}

.model-card__footer {
  display: flex;
  gap: 10px;
  align-items: center;
}

.model-card__failed-tip {
  font-size: 0.8rem;
  color: rgba(220, 234, 255, 0.5);
}

.op-btn {
  padding: 7px 16px;
  border: 1px solid rgba(125, 201, 255, 0.28);
  border-radius: 8px;
  background: rgba(91, 166, 255, 0.1);
  color: #9ad6ff;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.2s;
}

.op-btn:hover:not(:disabled) { background: rgba(91, 166, 255, 0.2); }

.op-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.op-btn--danger {
  border-color: rgba(255, 123, 114, 0.4);
  background: rgba(255, 123, 114, 0.12);
  color: #ffaaa3;
}

.op-btn--danger:hover:not(:disabled) { background: rgba(255, 123, 114, 0.24); }

.model-card__header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.card-chip-btn {
  padding: 4px 12px;
  border: 1px solid rgba(125, 201, 255, 0.28);
  border-radius: 999px;
  background: transparent;
  color: rgba(154, 214, 255, 0.7);
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}

.card-chip-btn:hover:not(:disabled) { background: rgba(91, 166, 255, 0.15); }

.card-chip-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.card-chip-btn--export {
  border-color: rgba(83, 229, 200, 0.32);
  background: rgba(83, 229, 200, 0.06);
  color: #9ee8d8;
}

.card-chip-btn--export:hover:not(:disabled) { background: rgba(83, 229, 200, 0.14); }

.card-chip-btn--danger {
  border-color: rgba(255, 123, 114, 0.32);
  background: rgba(255, 123, 114, 0.05);
  color: #ff9a93;
}

.card-chip-btn--danger:hover:not(:disabled) {
  background: rgba(255, 123, 114, 0.14);
  color: #ffb4ae;
}

/* 统一确认弹窗 */

.confirm-modal {
  position: fixed;
  inset: 0;
  z-index: 1400;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(3, 8, 16, 0.72);
  backdrop-filter: blur(4px);
}

.confirm-dialog {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px 16px;
  width: min(460px, 100%);
  padding: 22px;
  border: 1px solid rgba(125, 201, 255, 0.24);
  border-radius: 16px;
  background: linear-gradient(160deg, rgba(13, 26, 46, 0.98), rgba(8, 17, 31, 0.99));
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.58);
}

.confirm-dialog__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  font-size: 1.15rem;
  font-weight: 700;
}

.confirm-dialog__icon--primary {
  border: 1px solid rgba(83, 229, 200, 0.34);
  background: rgba(83, 229, 200, 0.1);
  color: #9ee8d8;
}

.confirm-dialog__icon--danger {
  border: 1px solid rgba(255, 123, 114, 0.4);
  background: rgba(255, 123, 114, 0.12);
  color: #ffaaa3;
}

.confirm-dialog__content h3 {
  margin: 1px 0 8px;
  color: #e8f1ff;
  font-size: 1.06rem;
}

.confirm-dialog__content p {
  margin: 0;
  color: rgba(220, 234, 255, 0.8);
  font-size: 0.9rem;
  line-height: 1.7;
}

.confirm-dialog__content .confirm-dialog__detail {
  margin-top: 6px;
  color: rgba(220, 234, 255, 0.52);
  font-size: 0.82rem;
}

.confirm-dialog__actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
  padding-top: 14px;
  border-top: 1px solid rgba(125, 201, 255, 0.1);
}

.confirm-dialog__actions .op-btn {
  min-width: 92px;
}

/* 对比弹窗 */

.compare-modal,
.model-evaluation-modal {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 20px;
  background: rgba(3, 8, 16, 0.72);
  backdrop-filter: blur(4px);
}

.compare-modal__card,
.model-evaluation-modal__card {
  display: flex;
  flex-direction: column;
  max-height: min(86vh, 940px);
  border-radius: 14px;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.55);
  overflow: hidden;
}

.compare-modal__card {
  width: min(1180px, 100%);
  border: 1px solid rgba(91, 166, 255, 0.28);
  /* 纯色：固定首列单元格背景要跟卡片一致，渐变对不上 */
  background: #0c1a2d;
}

.compare-modal__head,
.model-evaluation-modal__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px 14px;
  border-bottom: 1px solid rgba(125, 201, 255, 0.1);
}

.compare-modal__head h3 {
  margin: 0;
  color: #e8f1ff;
  font-size: 1.12rem;
}

.compare-modal__head-actions,
.model-evaluation-modal__head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.compare-modal__close,
.model-evaluation-modal__close {
  flex-shrink: 0;
  padding: 4px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(220, 234, 255, 0.6);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}

.compare-modal__close:hover,
.model-evaluation-modal__close:hover {
  background: rgba(91, 166, 255, 0.16);
  color: #e8f1ff;
}

/* 横向滚动条挂在表格这一层：它才会常驻在可视区底部，
   而不是跟着纵向内容一起被推到最下面 */

.compare-modal__body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
  padding: 8px 24px 16px;
}

.compare-modal__foot,
.model-evaluation-modal__foot {
  display: flex;
  justify-content: flex-end;
  padding: 12px 24px;
  border-top: 1px solid rgba(125, 201, 255, 0.1);
}

.compare-table-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
}

/* border-collapse 必须 separate，collapse 下 sticky 单元格的背景会漏 */

.compare-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.85rem;
}

.compare-table th {
  text-align: center;
  padding: 10px 12px;
  color: rgba(154, 214, 255, 0.85);
  font-weight: 600;
  border-bottom: 1px solid rgba(125, 201, 255, 0.15);
  white-space: nowrap;
}

.compare-table td {
  text-align: center;
  padding: 10px 12px;
  color: rgba(217, 232, 255, 0.9);
  border-bottom: 1px solid rgba(125, 201, 255, 0.06);
  white-space: nowrap;
}

/* 首列钉在左侧：横向滚动时始终看得到这一行是什么 */

.compare-table th:first-child,
.compare-table td:first-child {
  position: sticky;
  left: 0;
  z-index: 1;
  background: #0c1a2d;
}

.compare-table tbody tr td:first-child { color: rgba(220, 234, 255, 0.6); }

.compare-best {
  color: #53e5c8 !important;
  font-weight: 700;
}

/* 与最优值的差距（百分点，带正负号），仅非最优项显示 */

.compare-cell__delta {
  margin-left: 8px;
  color: #ff6b6b;
  font-size: 0.78rem;
  font-weight: 600;
}

/* AI 评价弹窗 */

.model-evaluation-modal__card {
  width: min(900px, 100%);
  border: 1px solid rgba(83, 229, 200, 0.24);
  background: linear-gradient(160deg, rgba(13, 26, 46, 0.97), rgba(8, 17, 31, 0.99));
}

.model-evaluation-modal__title h3 {
  margin: 0 0 6px;
  color: #e8f1ff;
  font-size: 1.12rem;
}

.model-evaluation-modal__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 24px 20px;
}

.model-evaluation-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  color: rgba(154, 214, 255, 0.85);
  font-size: 0.84rem;
}

/* 等待期的思维链：正文一到就被清空，所以这里只求「看得出在动」，不求好读 */

.model-evaluation-reasoning {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(125, 201, 255, 0.14);
  border-radius: 8px;
  background: rgba(10, 22, 40, 0.5);
}

.model-evaluation-reasoning__label {
  margin-bottom: 6px;
  color: rgba(154, 214, 255, 0.72);
  font-size: 0.78rem;
}

.model-evaluation-reasoning__text {
  max-height: 200px;
  overflow: auto;
  color: rgba(196, 214, 240, 0.66);
  font-size: 0.85rem;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.model-evaluation-loading__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #53e5c8;
  animation: model-evaluation-pulse 1s ease-in-out infinite;
}

@keyframes model-evaluation-pulse {
  0%,
  100% {
    opacity: 0.25;
    transform: scale(0.8);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.op-btn--quiet {
  background: transparent;
  color: rgba(220, 234, 255, 0.7);
}

.model-evaluation-modal__status,
.model-evaluation-modal__notice,
.model-evaluation-empty {
  margin-bottom: 14px;
  padding: 10px 12px;
  border-radius: 7px;
  background: rgba(91, 166, 255, 0.08);
  color: rgba(220, 234, 255, 0.72);
  font-size: 0.84rem;
}

.model-evaluation-modal__notice--error {
  background: rgba(255, 123, 114, 0.1);
  color: #ffaaa3;
}

.model-evaluation-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.model-evaluation-fact {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid rgba(125, 201, 255, 0.1);
  border-radius: 7px;
  background: rgba(8, 17, 31, 0.42);
}

.model-evaluation-fact span,
.model-evaluation-fields__label {
  color: rgba(220, 234, 255, 0.52);
  font-size: 0.76rem;
}

.model-evaluation-fact strong {
  overflow: hidden;
  color: #d9e8ff;
  font-size: 0.88rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-evaluation-fields {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.model-evaluation-field {
  padding: 4px 9px;
  border: 1px solid rgba(83, 229, 200, 0.2);
  border-radius: 6px;
  background: rgba(83, 229, 200, 0.06);
  color: #9ee8d8;
  font-size: 0.78rem;
}

.model-evaluation-markdown {
  padding-top: 4px;
  color: rgba(232, 241, 255, 0.88);
  font-size: 0.9rem;
  line-height: 1.7;
}

.model-evaluation-markdown :deep(h1),
.model-evaluation-markdown :deep(h2),
.model-evaluation-markdown :deep(h3) {
  margin: 16px 0 8px;
  color: #d9e8ff;
  font-size: 1rem;
}

.model-evaluation-markdown :deep(p),
.model-evaluation-markdown :deep(ul),
.model-evaluation-markdown :deep(ol) {
  margin: 7px 0;
}

.model-evaluation-markdown :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
  background: rgba(8, 17, 31, 0.65);
  color: #9ad6ff;
}

@media (max-width: 768px) {
  .model-card__meta {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .model-card__metrics { flex-wrap: wrap; }

  .confirm-modal,
  .compare-modal,
  .model-evaluation-modal { padding: 16px 12px; }

  .confirm-dialog { padding: 18px; }

  .compare-modal__card,
  .model-evaluation-modal__card { max-height: 90vh; }

  .compare-modal__head,
  .compare-modal__body,
  .compare-modal__foot,
  .model-evaluation-modal__head,
  .model-evaluation-modal__body,
  .model-evaluation-modal__foot {
    padding-left: 16px;
    padding-right: 16px;
  }

  .model-evaluation-modal__head-actions {
    width: 100%;
    justify-content: space-between;
  }

  .model-evaluation-modal__head-actions .op-btn { flex: 1; }

  .model-evaluation-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>

