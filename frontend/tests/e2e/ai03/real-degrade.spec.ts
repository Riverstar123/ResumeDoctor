import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { apiJson, confirmProfile, consent, startDiagnosis } from '../qa03/helpers';
import { JOB_FULL } from '../qa03db/helpers-db';
import {
  BAD_MODEL,
  EVIDENCE_DIR,
  assertNoContactLeak,
  uploadPdf,
  addConfirmedJob,
  waitTerminalReport,
} from './helpers-ai03';

// Explicit enhancement with an invalid provider model must preserve the base report.
test.describe('AI-03 真实供应商错误隔离', () => {
  test('坏模型名只影响建议，基础报告和评分依据不变', async ({ page }) => {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    await consent(page);
    await uploadPdf(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB_FULL);
    const id = await startDiagnosis(page);
    await waitTerminalReport(page);
    const base = await apiJson(page, 'GET', `/diagnoses/${id}`);
    expect(base.data.items[0].status).toBe('succeeded');
    expect(base.data.items[0].model_metadata).toBeNull();
    const score = base.data.items[0].score_result;
    const report = base.data.items[0].report;
    const analyze = page.getByRole('button', { name: '生成 AI 分析与改写' });
    await page.getByLabel('本次任务模型').selectOption(BAD_MODEL);
    await analyze.click();
    await expect(page.getByText(/本次未生成可用的新建议/)).toBeVisible({ timeout: 315000 });
    const after = await apiJson(page, 'GET', `/diagnoses/${id}`);
    expect(after.data.status).toBe('succeeded');
    expect(after.data.items[0].status).toBe('succeeded');
    expect(after.data.items[0].enhancement.status).toBe('failed');
    expect(after.data.items[0].enhancement.error.code).toBe('MODEL_UNAVAILABLE');
    expect(after.data.items[0].score_result).toEqual(score);
    expect(after.data.items[0].report).toEqual(report);
    expect(after.data.items[0].model_metadata).toBeNull();
    expect(after.data.model_id).toBeNull();
    await expect(analyze).toBeEnabled();
    await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeEnabled();
    const snapshot = JSON.stringify(after.data);
    assertNoContactLeak(snapshot);
    fs.writeFileSync(`${EVIDENCE_DIR}/03-diagnosis-degraded.json`, snapshot);
    await page.screenshot({ path: `${EVIDENCE_DIR}/03-report-degraded.png`, fullPage: true });
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    fs.writeFileSync(`${EVIDENCE_DIR}/03-report-degraded.md`, markdown);
    expect(markdown).toContain(`- 总分：${score.score.toFixed(1)} / 100`);
    expect(markdown).toContain(report.summary);
    expect(markdown).not.toContain('本岗位已降级为仅规则评分');
  });
});
