import type { Schema } from '../types';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
    public requestId = '',
    public retryAfter = 0,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
export type Transport = (input: string, init: RequestInit) => Promise<Response>;
export const isTerminal = (status: string) => ['succeeded', 'partial', 'failed'].includes(status);
export function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const abort = () => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', abort, { once: true });
  });
}
export function retrySeconds(value: string | null) {
  if (!value) return 0;
  const seconds = Number(value);
  return Number.isFinite(seconds)
    ? Math.max(0, seconds)
    : Math.max(0, (Date.parse(value) - Date.now()) / 1000) || 0;
}

export class ApiClient {
  constructor(
    private transport: Transport = (url, init) => fetch(url, init),
    private base = '/api/v1',
  ) {}
  async request<T>(
    path: string,
    options: {
      method?: string;
      body?: unknown;
      key?: string;
      signal?: AbortSignal;
      text?: boolean;
    } = {},
  ): Promise<T> {
    const method = options.method || 'GET';
    const multipart = options.body instanceof FormData;
    const headers = new Headers({ Accept: options.text ? 'text/markdown' : 'application/json' });
    if (options.body !== undefined && !multipart) headers.set('Content-Type', 'application/json');
    if (options.key) headers.set('Idempotency-Key', options.key);
    let response: Response;
    try {
      const timeout = AbortSignal.timeout(20_000);
      response = await this.transport(`${this.base.replace(/\/$/, '')}${path}`, {
        method,
        headers,
        credentials: 'include',
        body: multipart
          ? (options.body as FormData)
          : options.body === undefined
            ? undefined
            : JSON.stringify(options.body),
        signal: options.signal ? AbortSignal.any([options.signal, timeout]) : timeout,
      });
    } catch (error) {
      if (options.signal?.aborted) throw error;
      throw new ApiError(
        0,
        'NETWORK_ERROR',
        '连接中断或请求超时。请检查网络后重试，同一请求会沿用幂等键。',
      );
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as Schema['Error'] | null;
      const error = new ApiError(
        response.status,
        body?.error?.code || 'HTTP_ERROR',
        body?.error?.message || `请求失败（${response.status}）`,
        body?.error?.details || {},
        body?.request_id || '',
        retrySeconds(response.headers.get('Retry-After')),
      );
      if (response.status === 401 && typeof window !== 'undefined')
        window.dispatchEvent(new Event('rd:session-expired'));
      throw error;
    }
    if (response.status === 204) return undefined as T;
    if (options.text) return (await response.text()) as T;
    return (await response.json()) as T;
  }
  session = () =>
    this.request<Schema['Session']>('/session', {
      method: 'POST',
      body: { consent_version: 'v1' },
    });
  deleteSession = () => this.request<void>('/session', { method: 'DELETE' });
  models = (signal?: AbortSignal) => this.request<Schema['ModelList']>('/models', { signal });
  createProfile = (content: Schema['ProfileContent'], key: string) =>
    this.request<Schema['Profile']>('/profiles', { method: 'POST', body: { content }, key });
  profile = (id: string, version?: number, signal?: AbortSignal) =>
    this.request<Schema['Profile']>(
      `/profiles/${encodeURIComponent(id)}${version ? `?version=${version}` : ''}`,
      { signal },
    );
  saveProfile = (id: string, body: Schema['ProfileUpdate']) =>
    this.request<Schema['Profile']>(`/profiles/${id}`, { method: 'PUT', body });
  confirmProfile = (id: string, version: number) =>
    this.request<Schema['Profile']>(`/profiles/${id}/confirm`, {
      method: 'POST',
      body: { version },
    });
  messages = (id: string, signal?: AbortSignal) =>
    this.request<Schema['MessageList']>(`/profiles/${id}/messages`, { signal });
  sendMessage = (id: string, body: Schema['MessageCreate'], key: string) =>
    this.request<Schema['TaskAccepted']>(`/profiles/${id}/messages`, { method: 'POST', body, key });
  upload = (file: File, modelId: string, key: string) => {
    const body = new FormData();
    body.append('file', file);
    body.append('model_id', modelId);
    return this.request<Schema['TaskAccepted']>('/documents', { method: 'POST', body, key });
  };
  createJob = (body: Schema['JobCreate'], key: string) =>
    this.request<Schema['TaskAccepted']>('/jobs', { method: 'POST', body, key });
  job = (id: string, version?: number, signal?: AbortSignal) =>
    this.request<Schema['Job']>(
      `/jobs/${encodeURIComponent(id)}${version ? `?version=${version}` : ''}`,
      { signal },
    );
  saveJob = (id: string, body: Schema['JobUpdate']) =>
    this.request<Schema['Job']>(`/jobs/${id}`, { method: 'PUT', body });
  confirmJob = (id: string, version: number) =>
    this.request<Schema['Job']>(`/jobs/${id}/confirm`, { method: 'POST', body: { version } });
  diagnose = (body: Schema['DiagnosisCreate'], key: string) =>
    this.request<Schema['DiagnosisAccepted']>('/diagnoses', { method: 'POST', body, key });
  task = (id: string, signal?: AbortSignal) =>
    this.request<Schema['Task']>(`/tasks/${encodeURIComponent(id)}`, { signal });
  diagnosis = (id: string, signal?: AbortSignal) =>
    this.request<Schema['Diagnosis']>(`/diagnoses/${encodeURIComponent(id)}`, { signal });
  export = (id: string) => this.request<string>(`/diagnoses/${id}/export`, { text: true });
}

export async function pollTask(
  client: ApiClient,
  id: string,
  onUpdate: (task: Schema['Task']) => void | Promise<void>,
  signal: AbortSignal,
  interval = 2000,
) {
  while (!signal.aborted) {
    try {
      const task = await client.task(id, signal);
      if (signal.aborted) return;
      await onUpdate(task);
      if (isTerminal(task.status)) return;
      await delay(interval, signal);
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && error.status === 429) {
        await delay(Math.max(error.retryAfter * 1000, interval), signal);
      } else throw error;
    }
  }
}
