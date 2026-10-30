import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// AI-03 真实模型验收：真实 UI → http 模式 Vite 同源代理 → 生产 FastAPI
// （app.database 正式装配）→ 独立生产 worker（app.platform.jobs）→ 一次性
// PostgreSQL。业务模块全部走交付实现（真 PDF/DOCX 解析、ReportService
// 校验与正式 Markdown renderer、数据库队列与租约）。
//
// 模式由 RD_AI03_MODE 控制：
//   fake（默认）：开发调试用，不调用外部供应商，目录为 demo-model-a/b；
//   real：AI-03 显式真实验收，API/worker 从组长本地 backend/.env 读取端点、
//   实际模型与 key，目录为 real-default/real-model-a/real-model-b。
// real 模式还需要 RD_AI03_NOTICE 给出公开处理告知（实际供应商、用途、
// 外部传输）；该字段是公开文案，不含凭证。
//
// 前置（见 docs/08-development.md）：便携 PostgreSQL；RD_AI03_PG_HOME 或
// RD_QA03_PG_HOME 指向 pgsql 目录（含 bin/initdb.exe）。
const root = import.meta.dirname;
const backendDir = path.resolve(root, '../backend');
const python =
  process.env.RD_AI03_PYTHON ||
  process.env.RD_QA03_PYTHON ||
  (process.platform === 'win32'
    ? path.join(backendDir, '.venv/Scripts/python.exe')
    : path.join(backendDir, '.venv/bin/python'));

const pgHome = process.env.RD_AI03_PG_HOME || process.env.RD_QA03_PG_HOME;
if (!pgHome) {
  throw new Error(
    'AI-03 套件需要 RD_AI03_PG_HOME 或 RD_QA03_PG_HOME 指向便携 PostgreSQL 的 pgsql 目录',
  );
}

const mode = process.env.RD_AI03_MODE === 'real' ? 'real' : 'fake';
if (mode === 'real' && !process.env.RD_AI03_NOTICE) {
  throw new Error(
    'RD_AI03_MODE=real 时必须设置 RD_AI03_NOTICE：说明实际供应商、资料用途与外部传输的公开告知',
  );
}

export const ai03FixtureDir = path.join(root, 'test-results/ai03/fixtures');

// 真 PDF/DOCX 由后端固定生成器产出（tests.platform.int02_fixtures），
// 内容仅含登记合成素材；配置加载时生成一次，供上传用例 setInputFiles 使用。
execFileSync(python, ['-m', 'tests.platform.int02_fixtures', '--output', ai03FixtureDir], {
  cwd: backendDir,
  stdio: 'inherit',
});

const NOTICE =
  mode === 'real'
    ? process.env.RD_AI03_NOTICE!
    : 'AI-03 开发调试：合成资料 + fake 模型，不调用外部供应商。';

type Variant = {
  name: string;
  spec: string;
  backend: number;
  web: number;
  extra: string[];
  uploads: string;
  db: string;
};

const variants: Variant[] = [
  {
    name: 'success',
    spec: 'real-success.spec.ts',
    backend: 8030,
    web: 5200,
    extra: [],
    uploads: 'uploads',
    db: 'rd_ai03_success_test',
  },
];

// 真实降级变体：LLM_MODEL_A 覆盖为不存在的模型名，真实供应商返回配置错误。
// fake 开发模式下没有对应的故障机制，不启动该变体。该变体使用独立数据库，
// 两套 API/worker 同时存活时队列物理隔离（PR #60 复审 P2）。
if (mode === 'real') {
  variants.push({
    name: 'degrade',
    spec: 'real-degrade.spec.ts',
    backend: 8031,
    web: 5201,
    extra: ['--bad-model-a'],
    uploads: 'uploads-degrade',
    db: 'rd_ai03_degrade_test',
  });
}

export default defineConfig({
  testDir: './tests/e2e/ai03',
  timeout: 180000,
  expect: { timeout: 20000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: 'test-results/ai03',
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
      // webServer.command 经 shell 执行：Python 与 PG 路径可能含空格，
      // 必须整体加引号（PR #59 D/A 复审结论）。
      command:
        `"${python}" -m tests.e2e.serve_ai03 --port ${variant.backend} ` +
        `--origin http://127.0.0.1:${variant.web} --pg-home "${pgHome}" ` +
        `--llm-mode ${mode} --uploads-name ${variant.uploads} ` +
        `--db-name ${variant.db} ${variant.extra.join(' ')}`,
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
