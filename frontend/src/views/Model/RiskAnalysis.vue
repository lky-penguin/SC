<template>
  <div class="risk-analysis-page">
    <div class="page-inner">
      <section class="card train-card">
        <header class="train-card__head"><h3>训练配置</h3></header>
        <div class="train-section train-section--pair">
          <div class="form-group">
            <span class="section-label">数据集</span>
            <div class="field">
              <select v-model="selectedDatasetId" class="form-select" :disabled="loadingDatasets">
                <option v-if="loadingDatasets" value="" disabled>加载中…</option>
                <option v-else-if="!datasetList.length" value="" disabled>暂无数据集</option>
                <option v-for="ds in datasetList" :key="ds.id" :value="ds.id">
                  {{ ds.name }}（v{{ ds.version }} · {{ ds.fields_schema?.length ?? 0 }} 字段）{{ ds.status === 'ACTIVE' ? '' : '【已停用】' }}
                </option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <span class="section-label">算法</span>
            <div class="field">
              <select v-model="selectedAlgoId" class="form-select" :disabled="!algorithms.length">
                <option v-if="!algorithms.length" value="" disabled>暂无算法</option>
                <option
                  v-for="a in algorithms"
                  :key="a.id"
                  :value="a.id"
                  :disabled="!a.available"
                >{{ a.display_name }}</option>
              </select>
            </div>
          </div>
        </div>

        <div v-if="visibleParams.length" class="train-section">
          <span class="section-label">训练参数</span>
          <div class="param-grid">
            <div v-for="p in visibleParams" :key="p.param_name" class="param-item">
              <div class="param-item__head">
                <span class="param-item__label">{{ p.label }}</span>
                <span
                  v-if="p.type === 'number' && (p.min !== undefined || p.max !== undefined)"
                  class="param-item__range"
                >{{ p.min }} – {{ p.max }}</span>
              </div>
              <div v-if="p.type === 'select'" class="field">
                <select v-model="paramForm[p.param_name]" class="form-select">
                  <option v-for="o in p.options" :key="o.value" :value="o.value">{{ o.label }}</option>
                </select>
              </div>
              <input
                v-else-if="p.type === 'number'"
                v-model.number="paramForm[p.param_name]"
                type="number"
                class="form-input"
                :min="p.min"
                :max="p.max"
                :step="p.step ?? 'any'"
              />
              <input v-else v-model="paramForm[p.param_name]" type="text" class="form-input" />
            </div>
          </div>
        </div>

        <div class="train-actions">
          <button
            class="train-btn train-btn--primary"
            :class="{ 'is-running': training }"
            :disabled="training || !selectedDatasetId || !selectedAlgoId"
            @click="handleTrain"
          >
            <span v-if="training" class="btn-spinner"></span>
            {{ training ? '训练中' : '开始训练' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { AlgorithmParamDef } from '@/types/security';
import { useTrainingJobStore } from '@/stores/trainingJobStore';
import { getDatasets, getAlgorithms, trainModelAsync } from '@/api/trainingApi';
import type { DatasetRow } from '@/api/trainingApi';
import { ElMessage } from 'element-plus';

const PARAM_TYPES: Record<string, AlgorithmParamDef['type']> = {
  int: 'number', integer: 'number', float: 'number', number: 'number', bool: 'boolean', enum: 'select',
};
const NUMERIC_FIELD_TYPES = new Set(['numeric', 'real', 'float', 'double', 'int', 'integer', 'number']);
const datasetList = ref<DatasetRow[]>([]);
const selectedDatasetId = ref<number | ''>('');
const loadingDatasets = ref(false);
const algorithms = ref<Array<{ id: number; display_name: string; available: boolean; params: AlgorithmParamDef[] }>>([]);
const selectedAlgoId = ref<number | ''>('');
const paramForm = ref<Record<string, number | string | boolean>>({});

const mapBackendParams = (schema: unknown[]): AlgorithmParamDef[] => schema.map((raw) => {
  const item = (raw ?? {}) as Record<string, unknown>;
  return {
    param_name: String(item.name ?? ''),
    label: String(item.label ?? item.name ?? ''),
    type: PARAM_TYPES[String(item.type)] ?? 'string',
    default_value: (item.default as AlgorithmParamDef['default_value']) ?? '',
    min: item.min as number | undefined,
    max: item.max as number | undefined,
    step: item.step as number | undefined,
    options: Array.isArray(item.options)
      ? (item.options as { value: string; label: string }[])
      : Array.isArray(item.enum_values)
        ? (item.enum_values as string[]).map((value) => ({ value, label: value }))
        : undefined,
    description: String(item.description ?? ''),
    requires_numeric_features: Boolean(item.requires_numeric_features),
  };
});

const currentAlgo = computed(() => algorithms.value.find((item) => item.id === selectedAlgoId.value));
const datasetHasNumericFeatures = computed(() => {
  const dataset = datasetList.value.find((item) => item.id === selectedDatasetId.value);
  if (!dataset || !Array.isArray(dataset.fields_schema)) return false;
  return dataset.fields_schema.some((raw) => {
    const field = (raw ?? {}) as Record<string, unknown>;
    return field.role === 'feature' && NUMERIC_FIELD_TYPES.has(String(field.type ?? '').toLowerCase());
  });
});
const visibleParams = computed(() => {
  const params = currentAlgo.value?.params ?? [];
  return datasetHasNumericFeatures.value ? params : params.filter((item) => !item.requires_numeric_features);
});

const trainingJobStore = useTrainingJobStore();
const training = computed(() => Boolean(trainingJobStore.activeJob));
const trainJobTitle = computed(() => {
  const algorithm = algorithms.value.find((item) => item.id === selectedAlgoId.value)?.display_name;
  return algorithm ? `模型训练 · ${algorithm}` : '模型训练';
});

const loadDatasets = async () => {
  loadingDatasets.value = true;
  try {
    datasetList.value = (await getDatasets()).filter((item) => item.status === 'ACTIVE');
    selectedDatasetId.value = datasetList.value[0]?.id ?? '';
  } catch (err) {
    datasetList.value = [];
    ElMessage.warning(err instanceof Error ? err.message : '数据集加载失败');
  } finally {
    loadingDatasets.value = false;
  }
};

const resetParamForm = () => {
  paramForm.value = {};
  for (const param of visibleParams.value) paramForm.value[param.param_name] = param.default_value;
};
watch([selectedAlgoId, datasetHasNumericFeatures], resetParamForm);

const handleTrain = async () => {
  if (!selectedDatasetId.value) {
    ElMessage.warning('请先选择数据集版本');
    return;
  }
  if (!selectedAlgoId.value) {
    ElMessage.warning('请选择训练算法');
    return;
  }
  try {
    const training_parameters = Object.fromEntries(visibleParams.value
      .filter((param) => param.param_name in paramForm.value)
      .map((param) => [param.param_name, paramForm.value[param.param_name]]));
    const submitted = await trainModelAsync({
      dataset_id: selectedDatasetId.value,
      algorithm_id: selectedAlgoId.value,
      training_parameters,
    });
    trainingJobStore.track(submitted.id, trainJobTitle.value);
    ElMessage.success('训练已开始，完成后会通知你');
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '模型训练失败');
  }
};

onMounted(async () => {
  try {
    algorithms.value = (await getAlgorithms()).map((item) => ({
      id: item.id,
      display_name: item.display_name,
      available: item.status === 'AVAILABLE',
      params: mapBackendParams(item.param_schema ?? []),
    }));
  } catch (err) {
    ElMessage.warning(`加载算法数据失败：${err instanceof Error ? err.message : '请稍后重试'}`);
  }
  selectedAlgoId.value = algorithms.value.find((item) => item.available)?.id ?? '';
  await loadDatasets();
});
</script>

<style scoped>
.risk-analysis-page {
  position: relative;
  z-index: 1;
}

.page-inner {
  max-width: 1600px;
  margin: 0 auto;
}

.train-card {
  display: flex;
  flex-direction: column;
  padding: 26px 28px;
}

.train-card__head h3 {
  margin: 0;
  font-size: 1.12rem;
  font-weight: 600;
  color: #e8f1ff;
}

.train-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 22px;
  padding-top: 22px;
  border-top: 1px solid rgba(125,201,255,.12);
}

.train-section--pair {
  display: grid;
  grid-template-columns: repeat(2,minmax(0,1fr));
  gap: 22px;
}

.section-label {
  font-size: .78rem;
  letter-spacing: .05em;
  color: rgba(180,200,235,.6);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field {
  position: relative;
  display: block;
}

.form-select,
.form-input {
  width: 100%;
  height: 40px;
  box-sizing: border-box;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(125,201,255,.18);
  background: rgba(6,14,26,.7);
  color: #e8f1ff;
  font-size: .9rem;
  outline: none;
  color-scheme: dark;
  transition: border-color .18s ease,box-shadow .18s ease;
}

.form-select {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 38px;
  cursor: pointer;
}

.field::after {
  content: '';
  position: absolute;
  right: 16px;
  top: 50%;
  width: 7px;
  height: 7px;
  border-right: 1.6px solid rgba(160,200,255,.6);
  border-bottom: 1.6px solid rgba(160,200,255,.6);
  transform: translateY(-72%) rotate(45deg);
  pointer-events: none;
}

.form-select:focus,
.form-input:focus {
  border-color: rgba(125,201,255,.5);
  box-shadow: 0 0 0 3px rgba(91,166,255,.14);
}

.form-select:disabled,
.form-input:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.form-select option {
  background: #0b1628;
  color: #e8f1ff;
}

.param-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.param-item {
  flex: 1 1 200px;
  max-width: 300px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255,255,255,.028);
  border: 1px solid rgba(125,201,255,.09);
}

.param-item__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.param-item__label {
  font-size: .82rem;
  font-weight: 600;
  color: #d3e5ff;
}

.param-item__range {
  font-size: .72rem;
  color: rgba(160,200,255,.45);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.train-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 22px;
  padding-top: 22px;
  border-top: 1px solid rgba(125,201,255,.12);
}

.train-actions .train-btn--primary {
  width: auto;
  min-width: 180px;
  padding: 0 34px;
}

.train-btn {
  width: 100%;
  height: 44px;
  border: 1px solid transparent;
  border-radius: 12px;
  font-size: .95rem;
  font-weight: 600;
  letter-spacing: .02em;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: transform .18s ease,box-shadow .18s ease,background .18s ease,border-color .18s ease;
}

.train-btn--primary {
  color: #04121f;
  background: linear-gradient(135deg,#7dc9ff,#4f8ff0);
  box-shadow: 0 12px 28px rgba(45,108,200,.26);
}

.train-btn--primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 16px 34px rgba(45,108,200,.34);
}

.train-btn--primary.is-running {
  color: #04121f;
  background: linear-gradient(135deg,#7dc9ff,#4f8ff0);
  box-shadow: 0 10px 24px rgba(45,108,200,.22);
  cursor: default;
}

.train-btn--primary:disabled:not(.is-running) {
  color: rgba(200,222,255,.38);
  background: rgba(125,201,255,.12);
  border-color: rgba(125,201,255,.14);
  box-shadow: none;
  cursor: not-allowed;
}

.btn-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(4,18,31,.25);
  border-top-color: #04121f;
  border-radius: 50%;
  animation: spin .6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .train-section--pair { grid-template-columns: 1fr; }
}
</style>
