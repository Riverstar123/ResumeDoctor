import path from 'node:path';
import { expect, type Page } from '@playwright/test';

// AI-03：fake/real 两套目录 id 不同，脚本按 RD_AI03_MODE 选择断言目标。
export const REAL = process.env.RD_AI03_MODE === 'real';
export const DEFAULT_MODEL = REAL ? 'real-default' : 'demo-model-a';
export const SWITCH_MODEL = REAL ? 'real-model-b' : 'demo-model-b';
/** 降级变体中被覆盖为不存在实际模型名的公开条目。 */
export const BAD_MODEL = 'real-model-a';

export const EVIDENCE_DIR = 'test-results/ai03/evidence';
const FIXTURE_DIR = path.resolve(import.meta.dirname, '../../../test-results/ai03/fixtures');

/** 上传 tests.platform.int02_fixtures 生成的合成 PDF，走 M3 正式解析。 */
export async function uploadPdf(page: Page): Promise<string> {
  await page
    .getByLabel('选择简历文件')
    .setInputFiles(path.join(FIXTURE_DIR, 'synthetic-resume.pdf'));
  await page.getByRole('button', { name: /上传并整理档案/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  return page.url().split('/').filter(Boolean).pop()!;
}

/** 证据文件中不得出现联系方式（合成数据本身不含；防止过滤被绕过）。 */
export function assertNoContactLeak(text: string): void {
  expect(text).not.toMatch(/1[3-9](?:[ \t-]?\d){9}/);
  expect(text).not.toMatch(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
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
