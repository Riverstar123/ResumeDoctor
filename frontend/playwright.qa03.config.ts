import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// QA-03：真实 FastAPI（SyntheticIntake + 确定性评分 + FakeModelGateway 故障注入）
// 配真实 UI 的端到端验收，与 mock 套件（playwright.config.ts）和安全拦截套件
// （playwright.security.config.ts）完全隔离：独立端口、独立产物目录。
//
// 每个变体一对服务器：一个 tests.e2e.serve 后端 + 一个 http 模式 Vite。
// 故障开关只存在于后端进程环境，浏览器请求无法影响（CLAUDE.md：失败只由服务端注入）。
const root = import.meta.dirname;
const backendDir = path.resolve(root, '../backend');
const python =
  process.env.RD_QA03_PYTHON ||
  (process.platform === 'win32'
    ? path.join(backendDir, '.venv/Scripts/python.exe')
    : path.join(backendDir, '.venv/bin/python'));

const NOTICE =
  'QA-03 验收：后端使用合成档案与 fake 模型，失败均为服务端确定性注入，不调用外部模型。';

const variants = [
  { name: 'success', spec: 'real-stack-success.spec.ts', backend: 8010, web: 5180 },
  { name: 'partial', spec: 'real-stack-partial.spec.ts', backend: 8011, web: 5181 },
  { name: 'fail', spec: 'real-stack-fail.spec.ts', backend: 8012, web: 5182 },
  { name: 'slow', spec: 'real-stack-lifecycle.spec.ts', backend: 8013, web: 5183 },
] as const;

export default defineConfig({
  testDir: './tests/e2e/qa03',
  timeout: 90000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: process.env.RD_QA03_OUTPUT_DIR || 'test-results/qa03',
  use: {
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
  projects: variants.map((variant) => ({
    name: variant.name,
    testMatch: variant.spec,
    use: { baseURL: `http://127.0.0.1:${variant.web}` },
  })),
  webServer: variants.flatMap((variant) => [
    {
      // webServer.command 经 shell 执行：Python 路径可能含空格（仓库位于用户目录
      // 或 RD_QA03_PYTHON 指向 Program Files），必须整体加引号，否则 shell 会把
      // 空格前的部分当成程序名，浏览器用例执行前后端即退出（PR #59 D/A 复审）。
      command: `"${python}" -m tests.e2e.serve --variant ${variant.name} --port ${variant.backend} --origin http://127.0.0.1:${variant.web}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${variant.backend}/healthz`,
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: `npm run dev:api -- --port ${variant.web} --strictPort`,
      cwd: root,
      url: `http://127.0.0.1:${variant.web}`,
      reuseExistingServer: false,
      timeout: 120000,
      env: {
        VITE_API_MODE: 'http',
        VITE_API_BASE_URL: '/api/v1',
        VITE_PROCESSING_NOTICE: NOTICE,
        API_PROXY_TARGET: `http://127.0.0.1:${variant.backend}`,
      },
    },
  ]),
});
