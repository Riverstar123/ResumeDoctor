import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import {
  addConfirmedJob,
  chatProfile,
  confirmProfile,
  consent,
  EVIDENCE_DIR,
  JOB1,
  JOB2,
  startDiagnosis,
  waitTerminalReport,
} from './helpers';

// partial 变体：每两次 diagnosis_report 调用的第二次确定性 invalid_json
// （服务端注入，重试预算 1 次用尽后降级）。双岗位诊断中 JOB2 稳定为 score_only。
test.describe('QA-03 partial 变体：T11 报告失败降级 / T12 部分成功仍可导出', () => {
  test('一个岗位完整报告、另一个仅评分；任务 partial、导出保留两岗位', async ({ page }) => {
    await consent(page);
    await chatProfile(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB1);
    await addConfirmedJob(page, JOB2);
    await startDiagnosis(page);
    await waitTerminalReport(page);

    // 任务级 partial 提示，导出仍可用。
    await expect(
      page.locator('p.notice.warning', { hasText: '部分岗位或 AI 报告未完成' }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeEnabled();

    const tabs = page.getByRole('tab');
    await expect(tabs.first()).toContainText('66.7');
    await expect(tabs.first()).toContainText('已完成');
    await expect(tabs.nth(1)).toContainText('0.0');
    await expect(tabs.nth(1)).toContainText('仅评分');

    // 降级岗位：分数与规则明细保留，明确告知没有 AI 报告，错误码公开。
    await tabs.nth(1).click();
    await expect(page.getByText(/AI 报告未生成/)).toBeVisible();
    await expect(page.getByRole('heading', { name: '逐条要求与证据' })).toBeVisible();
    await expect(page.locator('#job-report').getByRole('alert')).toContainText(
      'MODEL_OUTPUT_INVALID',
    );
    await expect(page.locator('.report-columns')).toHaveCount(0);

    // 成功岗位：报告、模型元数据齐全。
    await page
      .getByRole('tab', { name: /数据开发课程演示岗位/ })
      .first()
      .click();
    await expect(page.locator('.report-summary')).toContainText('演示数据');
    await expect(page.locator('.model-metadata')).toContainText('demo-model-a');

    await page.screenshot({ path: `${EVIDENCE_DIR}/02-partial-score-only.png`, fullPage: true });

    // T12：导出的 Markdown 同时包含成功岗位与降级岗位及失败原因。
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const download = await downloadPromise;
    const markdown = fs.readFileSync((await download.path())!, 'utf8');
    expect(markdown).toContain('状态：partial');
    expect(markdown).toContain('66.7');
    expect(markdown).toContain('状态：score_only');
    expect(markdown).toContain('MODEL_OUTPUT_INVALID');
  });
});
