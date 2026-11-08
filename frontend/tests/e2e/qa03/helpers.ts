import { randomUUID } from 'node:crypto';
import { expect, type Page } from '@playwright/test';

// 唯一被 SyntheticIntake 识别的两份 JD 原文；服务端对未知原文明确失败。
export const JOB1 =
  '必须有 Python 项目应用经验。\n必须具备 SQL 应用能力。\n熟悉 Docker 优先。\n本科及以上学历优先。';
export const JOB2 = '平台运维合成岗位：必须具备 Kubernetes 应用能力。';

let keySeq = 0;
/** 合法幂等键（16–128 字符），只用于测试请求。 */
export function testKey(use: string): string {
  return `qa03-${use}-${++keySeq}-${randomUUID()}`;
}

export function resourceFromUrl(page: Page): string {
  return new URL(page.url()).pathname.split('/').filter(Boolean).pop()!;
}

export async function consent(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('checkbox', { name: /我已阅读/ }).check();
  await page.getByRole('button', { name: /同意并开始/ }).click();
  await expect(page.getByRole('heading', { name: '从真实经历开始' })).toBeVisible();
}

/** 对话输入路线：合成一句话经历，任务完成后落在档案页（真实链路下为 v2）。 */
export async function chatProfile(page: Page): Promise<string> {
  await page.getByRole('button', { name: '对话整理', exact: true }).click();
  await page
    .getByLabel('经历描述', { exact: true })
    .fill('合成经历：我在课程项目中使用 Python 清洗数据，了解 SQL 基本语法。');
  await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  return resourceFromUrl(page);
}

/** 上传输入路线：最小合法 PDF（%PDF- 魔数），由 SyntheticIntake 固定解析。 */
export async function uploadProfile(page: Page): Promise<string> {
  await page.getByLabel('选择简历文件').setInputFiles({
    name: 'synthetic-qa03.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-14 QA-03 synthetic fixture only\n%%EOF\n'),
  });
  await page.getByRole('button', { name: /上传并整理档案/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  return resourceFromUrl(page);
}

export async function confirmProfile(page: Page): Promise<void> {
  const button = page.getByRole('button', { name: /^确认档案 v\d+$/ });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(button).toBeDisabled();
  await page.getByRole('link', { name: /选择目标岗位/ }).click();
  await expect(page).toHaveURL(/\/jobs/);
}

/** 粘贴 JD 原文 → 提取 →（可选改名生成 v2）→ 确认。返回时该岗位已确认。 */
export async function addConfirmedJob(page: Page, raw: string, newTitle?: string): Promise<void> {
  await page.getByLabel('职位描述（JD）').fill(raw);
  await page.getByRole('button', { name: /提取岗位要求/ }).click();
  await expect(page.getByRole('button', { name: '确认 JD v1' })).toBeVisible();
  if (newTitle) {
    await page.getByLabel('岗位名称', { exact: true }).fill(newTitle);
    await page.getByRole('button', { name: '保存 JD 新版本' }).click();
    await expect(page.getByRole('button', { name: '确认 JD v2' })).toBeEnabled();
  }
  const button = page.getByRole('button', { name: /^确认 JD v\d+$/ });
  await button.click();
  await expect(button).toBeDisabled();
}

export async function startDiagnosis(page: Page): Promise<string> {
  await page.getByRole('button', { name: /开始诊断/ }).click();
  await expect(page).toHaveURL(/\/diagnoses\//);
  return resourceFromUrl(page);
}

export async function waitTerminalReport(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: '看清匹配，找到下一步。' })).toBeVisible();
}

export type ApiResult = { status: number; data: any };

/** 复用浏览器会话 Cookie 的真实 HTTP 调用（同源 /api/v1，经 Vite 代理）。 */
export async function apiJson(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
  key?: string,
): Promise<ApiResult> {
  return page.evaluate(
    async ({ method, path, body, key }) => {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (key) headers['Idempotency-Key'] = key;
      const response = await fetch(`/api/v1${path}`, {
        method,
        credentials: 'include',
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      let data: unknown = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }
      return { status: response.status, data };
    },
    { method, path, body, key },
  );
}

/** 直接 POST /documents 的 multipart 调用，绕过前端文件校验，验证服务端 413/415。 */
export async function apiUpload(
  page: Page,
  file: { name: string; contentType: string; bytes: Buffer },
  key: string,
): Promise<ApiResult> {
  const b64 = file.bytes.toString('base64');
  return page.evaluate(
    async ({ name, contentType, b64, key }) => {
      const binary = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const form = new FormData();
      form.append('file', new File([binary], name, { type: contentType }), name);
      form.append('model_id', 'demo-model-a');
      const response = await fetch('/api/v1/documents', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Idempotency-Key': key },
        body: form,
      });
      const text = await response.text();
      let data: unknown = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }
      return { status: response.status, data };
    },
    { name: file.name, contentType: file.contentType, b64, key },
  );
}

export async function pollTask(page: Page, taskId: string): Promise<any> {
  for (let i = 0; i < 100; i++) {
    const result = await apiJson(page, 'GET', `/tasks/${taskId}`);
    if (['succeeded', 'partial', 'failed'].includes(result.data?.status)) return result.data;
    await page.waitForTimeout(100);
  }
  throw new Error(`task ${taskId} did not reach a terminal state`);
}

export const EVIDENCE_DIR = 'test-results/qa03/evidence';

/** Report-model checks are explicit; base diagnosis itself is model-free. */
export async function enhanceAllReports(page: Page, model = 'demo-model-a'): Promise<void> {
  const id = new URL(page.url()).pathname.split('/').filter(Boolean).pop()!;
  const tabs = page.getByRole('tab');
  for (let index = 0; index < (await tabs.count()); index++) {
    await tabs.nth(index).click();
    await page.getByLabel('本次任务模型').selectOption(model);
    await page.getByRole('button', { name: '请求当前岗位建议' }).click();
    await expect
      .poll(
        async () => {
          const response = await apiJson(page, 'GET', `/diagnoses/${id}`);
          return response.data.items[index].enhancement?.status || 'not_started';
        },
        { timeout: 30000 },
      )
      .toMatch(/^(succeeded|partial|failed)$/);
    await expect(page.getByRole('button', { name: '请求当前岗位建议' })).toBeEnabled();
  }
  await tabs.first().click();
}
