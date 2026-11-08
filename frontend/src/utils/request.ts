import axios from 'axios';
import type { AxiosError, AxiosInstance, AxiosResponse } from 'axios';

interface ApiEnvelope<T> { code: number; message?: string; data?: T; }

export class RequestError extends Error {
  status?: number;
  code?: string;
  constructor(message: string, details: { status?: number; code?: string } = {}) {
    super(message);
    this.name = 'RequestError';
    this.status = details.status;
    this.code = details.code;
  }
}

const extractErrorMessage = (error: unknown): string => {
  const err = error as AxiosError<Record<string, unknown>> | undefined;
  const data = err?.response?.data;
  if (data && typeof data === 'object') {
    if (typeof data.message === 'string' && data.message) return data.message;
    if (typeof data.detail === 'string' && data.detail) return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => {
        const row = item as Record<string, unknown>;
        return String(row?.msg || row?.message || JSON.stringify(item));
      }).join('; ');
    }
  }
  return err?.message || '请求失败';
};

export const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 0,
});

service.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error: AxiosError) => Promise.reject(new RequestError(extractErrorMessage(error), {
    status: error.response?.status,
    code: error.code,
  })),
);

export const unwrapData = <T = unknown>(res: unknown): T => {
  const body = res as ApiEnvelope<T> | null | undefined;
  if (body?.code === 0) return body.data as T;
  throw new Error(body?.message || '请求失败');
};

export const consumeSse = async (
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): Promise<void> => {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const consume = (raw: string) => {
    buffer += raw;
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? '';
    for (const block of blocks) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1]?.trim();
      const dataText = block.match(/^data:\s*(.+)$/m)?.[1]?.trim();
      if (!event || !dataText) continue;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(dataText) as Record<string, unknown>;
      } catch {
        continue;
      }
      onEvent(event, data);
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    consume(decoder.decode(value, { stream: true }));
  }
  consume(decoder.decode());
};

export default service;
