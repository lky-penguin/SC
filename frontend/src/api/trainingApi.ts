import request, { unwrapData } from '@/utils/request';

export interface DatasetRow {
  id: number;
  name: string;
  version: number;
  status: string;
  file_path: string;
  fields_schema: unknown[];
  record_count?: number;
  field_count?: number;
}

export interface AlgorithmRow {
  id: number;
  code: string;
  display_name: string;
  description?: string | null;
  status: string;
  param_schema?: unknown[];
}

export interface ModelVersionRow {
  id: number;
  status?: string;
  evaluation_metrics?: { error?: string } | null;
}

export interface TrainingPayload {
  dataset_id: number;
  algorithm_id: number;
  training_parameters: Record<string, unknown>;
}

export const getDatasets = async (pageSize = 200): Promise<DatasetRow[]> => {
  const data = await unwrapData<{ items?: DatasetRow[] }>(await request.get('/api/v1/datasets', {
    params: { page: 1, page_size: pageSize },
  }));
  return data.items ?? [];
};

export const getAlgorithms = async (): Promise<AlgorithmRow[]> =>
  unwrapData(await request.get('/api/v1/algorithms'));

export const trainModel = async (payload: TrainingPayload): Promise<ModelVersionRow> =>
  unwrapData(await request.post('/api/v1/model-versions/train', payload));

export const trainModelAsync = async (payload: TrainingPayload): Promise<ModelVersionRow> =>
  unwrapData(await request.post('/api/v1/model-versions/train-async', payload));

export const getModelVersionDetail = async (modelId: number | string): Promise<ModelVersionRow> =>
  unwrapData(await request.get(`/api/v1/model-versions/${modelId}`));
