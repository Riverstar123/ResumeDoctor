import path from 'node:path';
import { expect, type Page } from '@playwright/test';
import { apiJson } from '../qa03/helpers';

// AI-03：fake/real 两套目录 id 不同，脚本按 RD_AI03_MODE 选择断言目标。
export const REAL = process.env.RD_AI03_MODE === 'real';
export const DEFAULT_MODEL = REAL ? 'real-default' : 'demo-model-a';
export const SWITCH_MODEL = REAL ? 'real-model-b' : 'demo-model-b';
/** 降级变体中被覆盖为不存在实际模型名的公开条目。 */
export const BAD_MODEL = 'real-model-a';
// M2 tasks have a persisted five-minute deadline. Allow its terminal update to
// reach the browser; UI assertions elsewhere retain the short expect timeout.
const TASK_WAIT_MS = REAL ? 315000 : 30000;

export async function waitTerminalReport(page: Page): Promise<void> {
  const id = page.url().split('/').filter(Boolean).pop()!;
  await expect
    .poll(
      async () => {
        const result = await apiJson(page, 'GET', `/diagnoses/${id}`);
        return result.status === 200 ? result.data.status : `HTTP_${result.status}`;
      },
      { timeout: TASK_WAIT_MS, intervals: [1000, 2000] },
    )
    .toMatch(/^(succeeded|partial|failed)$/);
  await expect(page.getByRole('heading', { name: '看清匹配，找到下一步。' })).toBeVisible();
}

export async function addConfirmedJob(page: Page, raw: string): Promise<void> {
  await page.getByLabel('职位描述（JD）').fill(raw);
  await page.getByRole('button', { name: /提取岗位要求/ }).click();
  const confirm = page.getByRole('button', { name: '确认 JD v1' });
  await expect(confirm).toBeVisible({ timeout: TASK_WAIT_MS });
  await confirm.click();
  await expect(confirm).toBeDisabled();
}

export const EVIDENCE_DIR = 'test-results/ai03/evidence';
const FIXTURE_DIR = path.resolve(import.meta.dirname, '../../../test-results/ai03/fixtures');

/** 上传 tests.platform.int02_fixtures 生成的合成 PDF，走 M3 正式解析。 */
export async function uploadPdf(page: Page): Promise<string> {
  await page
    .getByLabel('选择简历文件')
    .setInputFiles(path.join(FIXTURE_DIR, 'synthetic-resume.pdf'));
  await page.getByRole('button', { name: /上传并整理档案/ }).click();
  await expect(page).toHaveURL(/\/profiles\//, { timeout: TASK_WAIT_MS });
  return page.url().split('/').filter(Boolean).pop()!;
}

/** 证据文件中不得出现联系方式（合成数据本身不含；防止过滤被绕过）。 */
export function assertNoContactLeak(text: string): void {
  // 边界排除 UUID 误报：UUID 十六进制段可能恰好含 11 位手机号样式数字（实测
  // 段 144268871993），其前导为 '-' 或后续仍接十六进制字符，故要求号码两端
  // 不邻接单词字符或连字符；中文正文（\w 只覆盖 ASCII）不受影响。
  expect(text).not.toMatch(/(?<![\w-])1[3-9](?:[ \t-]?\d){9}(?![\w-])/);
  expect(text).not.toMatch(/(?<![\w.-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])/i);
}

type Diagnosis = {
  data: {
    items: Array<{
      status: string;
      score_result: { score: number } | null;
      model_metadata: { model_id: string; provider: string; model: string } | null;
    }>;
  };
};

/** M4 分数按岗位顺序取值；同一冻结快照换模型重诊必须逐岗位完全相同。 */
export function scoreValues(diagnosis: Diagnosis): number[] {
  return diagnosis.data.items.map((item) => item.score_result?.score ?? Number.NaN);
}
