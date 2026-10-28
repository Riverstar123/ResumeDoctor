import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// QA-03 正式栈验收：真实 UI → http 模式 Vite 同源代理 → 真实 FastAPI
// （app.database 正式装配）→ 独立 worker 进程 → 专用临时 PostgreSQL，
// 业务模块全部走交付实现（GatewayIntake 真 PDF/DOCX 解析、ReportService
// 校验与正式 Markdown renderer、数据库队列与租约），只有模型替换为
// 登记合成素材的 fake 网关。与轻量套件 playwright.qa03.config.ts 隔离。
//
// 前置（一次性，见 docs/08-development.md 与 docs/team/qa-03.md）：
//   1. EDB 便携版 PostgreSQL 解压到本机英文路径；
//   2. RD_QA03_PG_HOME 指向其 pgsql 目录（含 bin/initdb.exe）。
// 启动器自动 initdb/启动一次性集群、按变体建库并迁移，不注册系统服务。
const root = import.meta.dirname;
const backendDir = path.resolve(root, '../backend');
const python =
  process.env.RD_QA03_PYTHON ||
  (process.platform === 'win32'
    ? path.join(backendDir, '.venv/Scripts/python.exe')
    : path.join(backendDir, '.venv/bin/python'));

const pgHome = process.env.RD_QA03_PG_HOME;
if (!pgHome) {
  throw new Error(
    'QA-03 正式栈套件需要 RD_QA03_PG_HOME 指向便携 PostgreSQL 的 pgsql 目录（含 bin/initdb）',
  );
}

export const dbFixtureDir = path.join(root, 'test-results/qa03-db/fixtures');

// 真 PDF/DOCX 由后端固定生成器产出（tests.platform.int02_fixtures），
// 内容仅含登记合成素材；配置加载时生成一次，供上传用例 setInputFiles 使用。
execFileSync(python, ['-m', 'tests.platform.int02_fixtures', '--output', dbFixtureDir], {
  cwd: backendDir,
  stdio: 'inherit',
});

const NOTICE =
  'QA-03 正式栈验收：临时 PostgreSQL + 独立 worker + 合成资料与 fake 模型，失败均为服务端注入。';

const variants = [
  { name: 'success', spec: 'real-db-success.spec.ts', backend: 8020, web: 5190 },
  { name: 'partial', spec: 'real-db-partial.spec.ts', backend: 8021, web: 5191 },
  { name: 'revoke', spec: 'real-db-revoke.spec.ts', backend: 8022, web: 5192 },
] as const;

export default defineConfig({
  testDir: './tests/e2e/qa03db',
  timeout: 120000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: 'test-results/qa03-db',
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
      command:
        `${python} -m tests.e2e.serve_real --variant ${variant.name} ` +
        `--port ${variant.backend} --origin http://127.0.0.1:${variant.web} ` +
        `--pg-home "${pgHome}"`,
      cwd: backendDir,
      url: `http://127.0.0.1:${variant.backend}/healthz`,
      reuseExistingServer: false,
      timeout: 180000,
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
