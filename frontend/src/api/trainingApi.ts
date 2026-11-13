//训练相关接口的封装 注意 trainModelAsync 是异步训练，返回里只有 modelVersionId
//真正的训练状态要靠 stores/trainingJobStore 去轮询，这里别加同步等待
import request, { unwrapData } from '@/utils/request';
//只声明页面真用到的字段
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

export const trainModelAsync = async (payload: TrainingPayload): Promise<ModelVersionRow> =>
  unwrapData(await request.post('/api/v1/model-versions/train-async', payload));
//轮询用：只要 status 和 error
export const getModelVersionDetail = async (modelId: number | string): Promise<ModelVersionRow> =>
  unwrapData(await request.get(`/api/v1/model-versions/${modelId}`));
