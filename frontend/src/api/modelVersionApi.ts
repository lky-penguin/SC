//模型版本中心
import request, { unwrapData } from '@/utils/request';
import type { EvaluationMetrics, ModelStatus } from '@/types/security';

//与后端 ModelVersion 的字段保持一致
export interface BackendModelVersion {
  id: number;
  model_version_id: number;
  dataset_id: number;
  dataset_name?: string | null;
  dataset_version?: number | null;
  algorithm_id: number;
  algorithm_code?: string | null;
  algorithm_name?: string | null;
  training_parameters: Record<string, unknown>;
  evaluation_metrics: EvaluationMetrics;
  trained_at: string;
  status: ModelStatus;
  model_evaluation_available?: boolean;
  model_attributes?: Record<string, unknown>;
}
export interface ModelPackageExport {
  package_id: string;
  package_sha256: string;
  data_class: 'production' | 'test_fixture' | 'demo';
  display_label: string;
  status: string;
  exported_at: string | null;
}

export interface ModelVersionPage {
  items: BackendModelVersion[];
  total: number;
  page: number;
  page_size: number;
}
interface ModelVersionQuery {
  dataset_id?: string | number;
  page?: number;
  page_size?: number;
}

export const getModelVersionPage = async (params?: ModelVersionQuery): Promise<ModelVersionPage> => {
  const data = await unwrapData<Partial<ModelVersionPage>>(await request.get('/api/v1/model-versions', { params }));
  return { items: data.items ?? [], total: data.total ?? 0, page: data.page ?? 1, page_size: data.page_size ?? 10 };
};

export const deleteModelVersion = async (modelId: number | string): Promise<void> => {
  await unwrapData(await request.delete(`/api/v1/model-versions/${modelId}`));
};
//生成模型包（zip 打包+落盘），返回包元信息，下载要再调 GET
export const exportModelPackage = async (modelId: string | number): Promise<ModelPackageExport> =>
  unwrapData(await request.post(`/api/v1/model-versions/${modelId}/package`));

export const modelPackageDownloadUrl = (modelId: string | number): string =>
  `/api/v1/model-versions/${modelId}/package`;

//批量导出：一次请求打一个 zip 回来
export const exportModelPackages = async (modelIds: number[]): Promise<Blob> => {
  const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');
  const response = await fetch(`${baseUrl}/api/v1/model-versions/packages/export`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_ids: modelIds }),
  });
  if (!response.ok) {
    const text = await response.text();
    let message = `批量导出失败（HTTP ${response.status}）`;
    try {
      const body = JSON.parse(text) as { message?: string; detail?: string };
      message = body.message || body.detail || message;
    } catch {
      if (text.trim()) message = text.trim();
    }
    throw new Error(message);
  }
  return response.blob();
};
