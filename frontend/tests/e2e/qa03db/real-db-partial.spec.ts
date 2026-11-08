import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import {
  addConfirmedJob,
  confirmProfile,
  consent,
  startDiagnosis,
  waitTerminalReport,
} from '../qa03/helpers';
import { chatFullProfile, EVIDENCE_DIR, JOB_FULL, JOB_TEXTS } from './helpers-db';

// QA-03 正式栈 partial 变体：服务端按 diagnosis_report 调用序号确定性注入
// invalid_json（每 2 次的第 2 次失败），失败开关只来自 worker 进程环境，
// 请求体/JD 文本无法影响。双岗位中 JOB1 报告完成、JOB2 降级仅自动评分，
// 走的是交付的 ReportService 校验与正式 Markdown renderer。
test.describe('QA-03 正式栈 partial 变体', () => {
  test('一个岗位报告完成、另一个仅自动评分；任务 partial，正式 renderer 导出保留两岗位', async ({
    page,
  }) => {
    await consent(page);
    await chatFullProfile(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB_FULL);
    await addConfirmedJob(page, JOB_TEXTS[1]); // Kubernetes 无证据，黄金分 0
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

    // 降级岗位：自动评分保留，公开错误码 MODEL_OUTPUT_INVALID。
    await tabs.nth(1).click();
    await expect(page.getByText(/AI 报告未生成/)).toBeVisible();
    await expect(page.getByRole('heading', { name: '每条要求，逐项核对' })).toBeVisible();
    await expect(page.locator('#job-report').getByRole('alert')).toContainText(
      'MODEL_OUTPUT_INVALID',
    );
    await expect(page.locator('.report-columns')).toHaveCount(0);

    await page.screenshot({
      path: `${EVIDENCE_DIR}/09-real-partial-score-only.png`,
      fullPage: true,
    });

    // 正式 Markdown renderer（app/reporting/markdown.py）：完成/降级两种状态分段渲染。
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    expect(markdown).toContain('### 规则评分（由 M4 计算，报告不可修改）');
    expect(markdown).toContain('状态：partial');
    expect(markdown).toContain('- 结果状态：完成');
    expect(markdown).toContain('- 总分：66.7 / 100');
    expect(markdown).toContain('- 结果状态：仅规则评分（AI 报告未生成）');
    expect(markdown).toContain('AI 报告未生成，本岗位已降级为仅规则评分。');
    expect(markdown).toContain('- 错误码：MODEL_OUTPUT_INVALID');
    expect(markdown).toContain('- 模型选择：demo-model-a');
    expect(markdown).toContain('- 供应商：fake');
  });
});
