import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import {
  addConfirmedJob,
  chatProfile,
  confirmProfile,
  consent,
  EVIDENCE_DIR,
  apiJson,
  enhanceAllReports,
  JOB1,
  JOB2,
  startDiagnosis,
  waitTerminalReport,
} from './helpers';

// The second fake enhancement fails; both deterministic base reports survive.
test.describe('QA-03 partial 变体：建议失败隔离', () => {
  test('基础报告全部完成，一项建议失败仍可导出所有岗位', async ({ page }) => {
    await consent(page);
    await chatProfile(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB1);
    await addConfirmedJob(page, JOB2);
    const id = await startDiagnosis(page);
    await waitTerminalReport(page);
    const before = await apiJson(page, 'GET', `/diagnoses/${id}`);
    expect(before.data.status).toBe('succeeded');
    expect(
      before.data.items.every((item: { model_metadata: unknown }) => item.model_metadata === null),
    ).toBe(true);
    await enhanceAllReports(page);
    const after = await apiJson(page, 'GET', `/diagnoses/${id}`);
    expect(after.data.status).toBe('succeeded');
    expect(after.data.items[0].enhancement.status).toMatch(/succeeded|partial/);
    expect(after.data.items[1].enhancement.status).toBe('failed');
    expect(after.data.items[1].enhancement.error.code).toBe('MODEL_OUTPUT_INVALID');
    expect(after.data.items.map((item: { score_result: unknown }) => item.score_result)).toEqual(
      before.data.items.map((item: { score_result: unknown }) => item.score_result),
    );
    expect(after.data.items[1].report).toEqual(before.data.items[1].report);
    await expect(page.getByText(/本次未生成可用的新建议/)).toBeVisible();
    await expect(page.getByRole('heading', { name: '逐条要求与证据' })).toBeVisible();
    await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeEnabled();
    await page.screenshot({ path: `${EVIDENCE_DIR}/02-partial-score-only.png`, fullPage: true });
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    expect(markdown).toContain(before.data.items[0].report.summary);
    expect(markdown).toContain(before.data.items[1].report.summary);
    expect(markdown).not.toContain('本岗位已降级为仅规则评分');
  });
});
