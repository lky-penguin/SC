import request, { consumeSse, unwrapData } from '@/utils/request';
import type { DataPreview, Dataset, DatasetField, DatasetVersion } from '@/types/security';

interface ApiDataset {
  id: number;
  version: number;
  file_path: string;
  fields_schema?: ApiField[];
  label_field: string;
  uploaded_at: string;
  status: string;
  name?: string;
  file_name?: string;
  field_count?: number;
  data_format?: string;
  record_count?: number;
  referenced?: boolean;
  enabled?: boolean;
  change_type?: string | null;
  change_type_label?: string | null;
  is_breaking?: boolean;
  base_version_id?: number | null;
}

interface ApiField {
  name: string;
  type?: string;
  role?: string;
  enum_values?: string[];
  sample_values?: string[];
  description?: string;
}

interface ApiPreview {
  label_field: string;
  rows: Array<Record<string, string | number | null>>;
  page: number;
  page_size: number;
  total: number;
}

interface ApiPage<T> { items?: T[]; total?: number; page?: number; page_size?: number; }

const mapFieldType = (type?: string): string => {
  const normalized = (type || 'string').toLowerCase();
  if (['numeric', 'real', 'float', 'double'].includes(normalized)) return 'float';
  if (['integer', 'int'].includes(normalized)) return 'int';
  return normalized;
};

export const mapApiField = (field: ApiField, labelField?: string): DatasetField => {
  const isLabel = field.role === 'label' || Boolean(labelField && field.name === labelField);
  const samples = field.sample_values ?? [];
  return {
    field_name: field.name,
    field_type: mapFieldType(field.type),
    field_role: isLabel ? '分类标签' : '输入特征',
    description: field.description || '',
    sample_value: samples.length ? String(samples[0]) : '',
    nullable: !isLabel,
    enum_values: field.enum_values?.length ? field.enum_values.map(String) : undefined,
  };
};

const mapFields = (fields: ApiField[] | undefined, labelField?: string): DatasetField[] =>
  (fields ?? []).map((field) => mapApiField(field, labelField));

const mapCommon = (item: ApiDataset) => {
  const fields = mapFields(item.fields_schema, item.label_field);
  return {
    name: item.name || '未命名数据集',
    description: '',
    record_count: Number(item.record_count || 0),
    field_count: Number(item.field_count || fields.length),
    fields,
    data_format: (item.data_format as Dataset['data_format']) || 'arff',
    enabled: Boolean(item.enabled),
    referenced: Boolean(item.referenced),
    change_type: item.change_type,
    change_type_label: item.change_type_label,
    is_breaking: Boolean(item.is_breaking),
    base_version_id: item.base_version_id,
  };
};

const mapApiDataset = (item: ApiDataset): Dataset => ({
  ...mapCommon(item),
  dataset_id: String(item.id),
  file_name: item.file_name,
  created_at: item.uploaded_at,
  dataset_version: `v${item.version}`,
  label_field: item.label_field,
});

const mapApiDatasetVersion = (item: ApiDataset): DatasetVersion => ({
  ...mapCommon(item),
  dataset_version_id: String(item.id),
  dataset_id: String(item.id),
  dataset_version: `v${item.version}`,
  file_path: item.file_path,
  uploaded_at: item.uploaded_at,
});

const fetchDatasetItems = async (pageSize = 200): Promise<ApiDataset[]> => {
  const data = await unwrapData<ApiPage<ApiDataset>>(await request.get('/api/v1/datasets', {
    params: { page: 1, page_size: pageSize },
  }));
  return data.items ?? [];
};

export const getDatasetList = async (): Promise<Dataset[]> =>
  (await fetchDatasetItems()).map(mapApiDataset);

export const getDatasetDetail = async (datasetId: string | number): Promise<Dataset> =>
  mapApiDataset(await unwrapData<ApiDataset>(await request.get(`/api/v1/datasets/${datasetId}`)));

export const getDatasetFields = async (datasetId: string | number, _version?: string): Promise<DatasetField[]> => {
  const data = await unwrapData<{ fields_schema?: ApiField[]; label_field?: string }>(
    await request.get(`/api/v1/datasets/${datasetId}/fields-schema`),
  );
  return mapFields(data.fields_schema, data.label_field);
};

export const getDatasetPreview = async (
  datasetId: string | number,
  params: { page: number; page_size: number },
): Promise<DataPreview> => {
  const data = await unwrapData<ApiPreview>(await request.get(`/api/v1/datasets/${datasetId}/preview`, {
    params: { page: params.page, page_size: Math.min(50, Math.max(1, params.page_size)) },
  }));
  return {
    total: data.total ?? 0,
    page: data.page ?? params.page,
    page_size: data.page_size ?? params.page_size,
    label_field: data.label_field ?? '',
    rows: (data.rows ?? []).map((row) => Object.fromEntries(
      Object.entries(row || {}).map(([key, value]) => [key, value == null ? '' : value]),
    )),
  };
};

export const getDatasetVersions = async (datasetId?: string): Promise<DatasetVersion[]> => {
  if (!datasetId) return (await fetchDatasetItems()).map(mapApiDatasetVersion);
  const data = await unwrapData<ApiPage<ApiDataset>>(
    await request.get(`/api/v1/datasets/${datasetId}/versions`),
  );
  return (data.items ?? []).map(mapApiDatasetVersion);
};

export const uploadDatasetFile = async (params: {
  file: File;
  name: string;
}): Promise<Dataset> => {
  const form = new FormData();
  form.append('file', params.file);
  form.append('name', params.name.trim());
  return mapApiDataset(await unwrapData<ApiDataset>(await request.post('/api/v1/datasets/upload', form)));
};

export const appendDatasetRows = async (datasetId: string | number, file: File): Promise<DatasetVersion> => {
  const form = new FormData();
  form.append('file', file);
  return mapApiDatasetVersion(await unwrapData<ApiDataset>(
    await request.post(`/api/v1/datasets/${datasetId}/revisions/append`, form),
  ));
};

export interface DatasetRevisionItem {
  id: number;
  dataset_id: number;
  change_type: string;
  change_type_label: string;
  is_breaking: boolean;
  mode: 'in_place' | 'new_version';
  result_dataset_id: number | null;
  reason: string | null;
  summary: string | null;
  created_at: string | null;
}

export const getDatasetRevisions = async (datasetId: string | number): Promise<DatasetRevisionItem[]> => {
  const data = await unwrapData<{ items?: DatasetRevisionItem[] }>(
    await request.get(`/api/v1/datasets/${datasetId}/revisions`),
  );
  return data.items ?? [];
};

export const disableDatasetVersion = async (versionId: string | number): Promise<void> => {
  await unwrapData(await request.post(`/api/v1/datasets/${versionId}/disable`));
};

export const deleteDatasetVersion = async (versionId: string | number): Promise<void> => {
  await unwrapData(await request.delete(`/api/v1/datasets/${versionId}`));
};

export interface DatasetAnalysisResponse {
  dataset_id: number;
  name: string;
  available: boolean;
  source?: 'ai' | 'fallback' | 'cached' | null;
  markdown?: string | null;
  generated_at?: string | null;
}

export const getDatasetAiAnalysis = async (datasetId: string | number): Promise<DatasetAnalysisResponse> =>
  unwrapData(await request.get(`/api/v1/datasets/${datasetId}/ai-analysis`));

export interface DatasetAnalysisStreamHandlers {
  onStart?: (data: Record<string, unknown>) => void;
  onReasoning?: (content: string) => void;
  onDelta?: (content: string) => void;
  onError?: (message: string) => void;
  onDone?: (data: Record<string, unknown>) => void;
}

export const streamDatasetAiAnalysis = async (
  datasetId: string | number,
  handlers: DatasetAnalysisStreamHandlers,
  signal?: AbortSignal,
  regenerate = false,
): Promise<void> => {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/v1/datasets/${datasetId}/ai-analysis/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regenerate }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`AI 解析请求失败（${response.status}）`);
  await consumeSse(response.body, (event, data) => {
    if (event === 'start') handlers.onStart?.(data);
    else if (event === 'reasoning' && typeof data.content === 'string') handlers.onReasoning?.(data.content);
    else if (event === 'delta' && typeof data.content === 'string') handlers.onDelta?.(data.content);
    else if (event === 'error') handlers.onError?.(String(data.message ?? 'AI 解析失败'));
    else if (event === 'done') handlers.onDone?.(data);
  });
};
