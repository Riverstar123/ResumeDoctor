import path from 'node:path';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

// 正式栈只认 app.platform.demo_gateway 登记的合成原文（中文必须逐字一致）：
// JOB_TEXTS 顺序对应 INT-02 实测黄金分 66.7 / 0 / 100 / 50 / 0。
export const PROFILE_FULL =
  '使用 Python 完成课程数据清洗项目。\n了解 SQL 基本语法。\n已获得计算机相关专业本科学位。';
export const JOB_FULL =
  '必须有 Python 项目应用经验。\n必须具备 SQL 应用能力。\n熟悉 Docker 优先。\n本科及以上学历优先。';
export const JOB_TEXTS = [
  JOB_FULL,
  '必须具备 Kubernetes 应用能力。',
  '必须有 Python 项目应用经验。',
  '必须具备 SQL 应用能力。',
  '必须具备 Docker 应用能力。',
];
export const GOLDEN_SCORES = ['66.7', '0.0', '100.0', '50.0', '0.0'];

export const DB_FIXTURE_DIR = path.resolve(
  import.meta.dirname,
  '../../../test-results/qa03-db/fixtures',
);
export const EVIDENCE_DIR = 'test-results/qa03-db/evidence';

/** 上传真实可解析的合成 PDF/DOCX（tests.platform.int02_fixtures 生成），走 M3 正式解析。 */
export async function uploadReal(
  page: Page,
  fileName: 'synthetic-resume.pdf' | 'synthetic-resume.docx',
) {
  await page.getByLabel('选择简历文件').setInputFiles(path.join(DB_FIXTURE_DIR, fileName));
  await page.getByRole('button', { name: /上传并整理档案/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  return page.url().split('/').filter(Boolean).pop()!;
}

/** 对话路线：首条消息即完整登记素材（一次性给出三行事实，正式 fake 网关识别全文）。 */
export async function chatFullProfile(page: Page): Promise<string> {
  await page.getByRole('button', { name: '对话整理', exact: true }).click();
  await page.getByLabel('经历描述', { exact: true }).fill(PROFILE_FULL);
  await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  return page.url().split('/').filter(Boolean).pop()!;
}

/**
 * 第二轮对话补充：ProfilePage 的「补充经历」。
 * 成功后的稳定信号是完成 effect 清空输入框（ProfilePage setChat('')）并重新读取
 * 新版本；不能等「发送补充」重新 enabled——成功后按钮因 !chat.trim() 恰好稳定
 * 禁用，enabled 只出现在任务完成与清空之间的瞬时窗口，漏捕即误超时。
 * 版本升级由调用方的「确认档案 vN」断言校验；任务失败时输入框保留原文，本等待超时暴露失败。
 */
export async function sendProfileSupplement(page: Page, text: string): Promise<void> {
  await page.getByLabel('补充经历').fill(text);
  await page.getByRole('button', { name: '发送补充' }).click();
  await expect(page.getByLabel('补充经历')).toHaveValue('', { timeout: 30000 });
}

export async function sessionToken(page: Page): Promise<string> {
  const url = new URL(page.url());
  const cookies = await page.context().cookies();
  const cookie = cookies.find((item) => item.name === 'rd_session' && item.domain === url.hostname);
  if (!cookie) throw new Error('rd_session cookie missing');
  return cookie.value;
}

type E2eState = {
  session_id: string | null;
  revoked: boolean;
  counts: Record<string, number>;
  blocked: boolean;
  released: boolean;
  events: Array<{ seq: number; ts: number; event: string; task_id: string | null }>;
};

export async function e2eState(
  request: APIRequestContext,
  token: string,
  sid?: string,
): Promise<E2eState> {
  const query = new URLSearchParams({ token });
  if (sid) query.set('sid', sid);
  const response = await request.get(`/api/e2e/state?${query.toString()}`);
  if (!response.ok()) throw new Error(`/api/e2e/state ${response.status()}`);
  return response.json();
}

export async function releaseBarrier(request: APIRequestContext): Promise<void> {
  const response = await request.post('/api/e2e/release');
  expect(response.status()).toBe(204);
}

/** 轮询直到 worker 的 diagnosis_report 调用进入同步屏障。 */
export async function waitBlocked(request: APIRequestContext, token: string): Promise<E2eState> {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const state = await e2eState(request, token);
    if (state.blocked && state.session_id) return state;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('worker never reached the report barrier');
}

/**
 * 撤销放行后，worker 下一轮 cleanup_expired 会物理清除会话及其子表行。
 * 轮询十张业务表直到该 sid 全部为 0，证明没有任务结果、档案或诊断迟到写回。
 */
export async function waitZeroResidue(
  request: APIRequestContext,
  token: string,
  sid: string,
): Promise<E2eState> {
  for (let attempt = 0; attempt < 150; attempt += 1) {
    const state = await e2eState(request, token, sid);
    if (Object.values(state.counts).every((count) => count === 0)) return state;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const final = await e2eState(request, token, sid);
  throw new Error(`revoked session still has table residues: ${JSON.stringify(final.counts)}`);
}

/** 放行后等待目标任务的迭代在 worker 侧收尾，用于判定迟到写回是否被栅栏挡住。 */
export async function waitIterationDone(
  request: APIRequestContext,
  token: string,
  sid: string,
  taskId: string,
  since: number,
): Promise<E2eState> {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const state = await e2eState(request, token, sid);
    if (
      state.events.some(
        (event) =>
          event.event === 'iteration_done' && event.task_id === taskId && event.ts >= since - 1,
      )
    ) {
      return state;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('worker iteration never finished after release');
}
