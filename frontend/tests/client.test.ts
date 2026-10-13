import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, pollTask, retrySeconds } from '../src/api/client';
import type { Task } from '../src/types';

afterEach(() => vi.useRealTimers());
describe('HTTP contract', () => {
  it('sends credentials, snake_case, a stable supplied key and exact historical version', async () => {
    const transport = vi.fn(async (_url: string, _init: RequestInit) =>
      Response.json({ task_id: 'task' }),
    );
    const client = new ApiClient(transport);
    const body = {
      profile: { id: 'p', version: 2 },
      jobs: [{ id: 'j', version: 3 }],
      model_id: 'model-b',
    };
    await client.diagnose(body, 'stable-idempotency-key');
    expect(transport).toHaveBeenCalledWith(
      '/api/v1/diagnoses',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify(body),
      }),
    );
    expect(new Headers(transport.mock.calls[0][1].headers).get('Idempotency-Key')).toBe(
      'stable-idempotency-key',
    );
    await client.profile('profile', 2);
    expect(transport.mock.calls[1][0]).toBe('/api/v1/profiles/profile?version=2');
  });
  it('does not set JSON content type for multipart uploads', async () => {
    const transport = vi.fn(async (_url: string, _init: RequestInit) =>
      Response.json({ task_id: 'task' }),
    );
    await new ApiClient(transport).upload(
      new File(['test'], 'resume.pdf'),
      'model-a',
      'upload-idempotency-key',
    );
    const init = transport.mock.calls[0][1];
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
    expect((init.body as FormData).get('model_id')).toBe('model-a');
  });
  it.each([401, 404, 409, 413, 415, 422, 429])(
    'preserves structured HTTP %s errors',
    async (status) => {
      const client = new ApiClient(async () =>
        Response.json(
          {
            error: { code: 'CODE', message: '修正资料', details: { raw_text: '过长' } },
            request_id: 'request-1',
          },
          { status, headers: { 'Retry-After': '3' } },
        ),
      );
      await expect(client.models()).rejects.toMatchObject({
        status,
        code: 'CODE',
        details: { raw_text: '过长' },
        requestId: 'request-1',
        retryAfter: 3,
      });
    },
  );
  it('supports HTTP date Retry-After and network errors', async () => {
    expect(retrySeconds(new Date(Date.now() + 10000).toUTCString())).toBeGreaterThan(8);
    await expect(
      new ApiClient(async () => {
        throw new TypeError('offline');
      }).models(),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });
});
const task = (status: Task['status']): Task => ({
  id: 't',
  kind: 'diagnosis',
  model_id: 'm',
  status,
  result: null,
  error: null,
  created_at: '',
  updated_at: '',
});
describe('polling', () => {
  it('stops at a terminal state', async () => {
    vi.useFakeTimers();
    const client = new ApiClient();
    const get = vi
      .spyOn(client, 'task')
      .mockResolvedValueOnce(task('running'))
      .mockResolvedValue(task('partial'));
    const update = vi.fn();
    const promise = pollTask(client, 't', update, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(10000);
    await promise;
    expect(get).toHaveBeenCalledTimes(2);
    expect(update.mock.calls.at(-1)?.[0].status).toBe('partial');
  });
  it('aborts on unmount without issuing another poll', async () => {
    vi.useFakeTimers();
    const client = new ApiClient();
    const get = vi.spyOn(client, 'task').mockResolvedValue(task('running'));
    const controller = new AbortController();
    const promise = pollTask(client, 't', vi.fn(), controller.signal);
    await vi.advanceTimersByTimeAsync(100);
    controller.abort();
    await promise;
    await vi.advanceTimersByTimeAsync(10000);
    expect(get).toHaveBeenCalledTimes(1);
  });
  it('honors Retry-After before the next task poll', async () => {
    vi.useFakeTimers();
    const client = new ApiClient();
    const get = vi
      .spyOn(client, 'task')
      .mockRejectedValueOnce(new ApiError(429, 'RATE_LIMITED', 'wait', {}, '', 5))
      .mockResolvedValue(task('succeeded'));
    const promise = pollTask(client, 't', vi.fn(), new AbortController().signal);
    await vi.advanceTimersByTimeAsync(4999);
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await promise;
    expect(get).toHaveBeenCalledTimes(2);
  });
});
