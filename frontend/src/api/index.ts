import { ApiClient } from './client';
export const isMock = import.meta.env.VITE_API_MODE === 'mock';
// The mock transport is loaded only in explicit mock mode; HTTP errors never fall back to it.
export const api = new ApiClient(
  isMock ? async (url, init) => (await import('./mock')).mockFetch(url, init) : undefined,
  import.meta.env.VITE_API_BASE_URL || '/api/v1',
);
