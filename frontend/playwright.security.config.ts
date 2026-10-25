import { defineConfig, devices } from '@playwright/test';

// Separate server/output from the ordinary workflow suite and any user's dev server.
// API responses in this suite are intercepted by Playwright; no backend/model is used.
const port = 5179;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/security.spec.ts',
  timeout: 30000,
  expect: { timeout: 10000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: process.env.RD_SECURITY_OUTPUT_DIR || 'test-results/security',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    // Default Chromium remains portable; an already installed Edge can be chosen locally.
    channel: process.env.RD_SECURITY_BROWSER_CHANNEL || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
  webServer: {
    command: `npm run dev:api -- --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    env: {
      VITE_API_MODE: 'http',
      VITE_API_BASE_URL: '/api/v1',
      VITE_PROCESSING_NOTICE: '安全验收：接口由测试拦截，仅使用合成资料，不调用外部模型。',
    },
  },
});
