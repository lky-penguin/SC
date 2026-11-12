//模型评价接口
//普通查询走 GET，返回已有评价
import request, { consumeSse, unwrapData } from '@/utils/request';

export interface ModelEvaluationAttributes extends Record<string, unknown> {
  algorithm?: { name?: string | null; code?: string | null };
  dataset?: { name?: string | null };
  feature_profile?: Array<{ name: string; display_name?: string | null; [key: string]: unknown }>;
}

export interface ModelEvaluationResponse {
  model_version_id: number;
  status: string;
  role: 'current';
  model_attributes: ModelEvaluationAttributes;
  evaluation: {
    available: boolean;
    source?: 'ai' | 'fallback' | 'cached' | null;
    markdown?: string | null;
    generated_at?: string | null;
  };
}
export type ModelEvaluationAudience = 'current';

export interface ModelEvaluationStreamHandlers {
  onStart?: (data: Record<string, unknown>) => void;
  onReasoning?: (content: string) => void;
  onDelta?: (content: string) => void;
  onError?: (data: Record<string, unknown>) => void;
  onDone?: (data: Record<string, unknown>) => void;
}
export const getModelEvaluation = async (modelId: number): Promise<ModelEvaluationResponse> =>
  unwrapData(await request.get(`/api/v1/model-versions/${modelId}/evaluation`));

//流式生成评价 EventSource，fetch + 自己解 SSE
export const streamModelEvaluation = async (
  modelId: number,
  regenerate: boolean,
  handlers: ModelEvaluationStreamHandlers,
  signal?: AbortSignal,
): Promise<void> => {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/v1/model-versions/${modelId}/evaluation/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regenerate }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`模型评价请求失败（${response.status}）`);
  await consumeSse(response.body, (event, data) => {
    //reasoning 和 delta 分开推，页面上一个是灰字思考过程，一个是正文
    if (event === 'start') handlers.onStart?.(data);
    else if (event === 'reasoning' && typeof data.content === 'string') handlers.onReasoning?.(data.content);
    else if (event === 'delta' && typeof data.content === 'string') handlers.onDelta?.(data.content);
    else if (event === 'error') handlers.onError?.(data);
    else if (event === 'done') handlers.onDone?.(data);
  });
};
