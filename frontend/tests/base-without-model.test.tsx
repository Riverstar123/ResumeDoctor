import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AppProvider, useApp } from '../src/state';
import { api, isMock } from '../src/api';
import { ApiError } from '../src/api/client';

function Consumer() {
  const app = useApp();
  return (
    <>
      <p>{app.ready ? '基础功能可用' : '等待会话'}</p>
      <p>{app.error ? '模型目录不可用' : ''}</p>
    </>
  );
}
afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});
it('keeps base functionality available when the model catalog is unavailable', async () => {
  sessionStorage.setItem(
    `rd:workspace:${isMock ? 'mock' : 'http'}`,
    JSON.stringify({ session: { id: 'existing-session' } }),
  );
  vi.spyOn(api, 'models').mockRejectedValue(
    new ApiError(503, 'MODEL_UNAVAILABLE', 'synthetic unavailable'),
  );
  render(
    <AppProvider>
      <Consumer />
    </AppProvider>,
  );
  await screen.findByText('模型目录不可用');
  expect(screen.getByText('基础功能可用')).toBeInTheDocument();
});
it('still revokes the local session when a resource reports expiration', async () => {
  sessionStorage.setItem(
    `rd:workspace:${isMock ? 'mock' : 'http'}`,
    JSON.stringify({ session: { id: 'existing-session' } }),
  );
  vi.spyOn(api, 'models').mockResolvedValue({ items: [], default_model_id: 'unavailable' });
  render(
    <AppProvider>
      <Consumer />
    </AppProvider>,
  );
  await screen.findByText('基础功能可用');
  window.dispatchEvent(new Event('rd:session-expired'));
  await waitFor(() => expect(screen.getByText('等待会话')).toBeInTheDocument());
});
