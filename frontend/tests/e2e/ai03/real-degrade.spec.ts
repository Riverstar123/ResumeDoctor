import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import {
  addConfirmedJob,
  apiJson,
  confirmProfile,
  consent,
  startDiagnosis,
  waitTerminalReport,
} from '../qa03/helpers';
import { JOB_FULL } from '../qa03db/helpers-db';
import {
  BAD_MODEL,
  DEFAULT_MODEL,
  EVIDENCE_DIR,
  assertNoContactLeak,
  uploadPdf,
} from './helpers-ai03';

// AI-03 真实降级验收（仅 real 变体）：LLM_MODEL_A 被启动器覆盖为不存在的
// 模型名，供应商对 diagnosis_report 真实返回配置错误（MODEL_UNAVAILABLE，
// 不重试）。岗位必须保留 M4 评分并降级为 score_only，不伪造报告成功。
//
// 不硬编码 66.7：真实提取语义不同（A 的真实模块测试中该快照为 50.0），
// 改为记录降级前的真实分数，断言降级后完全一致——评分只由冻结快照决定。
test.describe('AI-03 真实供应商错误降级', () => {
  test('坏模型名导致报告失败，岗位保留评分降级仅规则评分', async ({ page }) => {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

    await consent(page);
    await uploadPdf(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB_FULL);

    // 默认模型先成功，证明端点/key 有效；坏的是模型名而不是整条链路。
    const firstId = await startDiagnosis(page);
    await waitTerminalReport(page);
    const first = await apiJson(page, 'GET', `/diagnoses/${firstId}`);
    expect(first.data.items[0].status).toBe('succeeded');
    expect(first.data.items[0].model_metadata.model_id).toBe(DEFAULT_MODEL);
    const expectedScore = first.data.items[0].score_result.score;
    await expect(page.getByRole('tab').first()).toContainText(expectedScore.toFixed(1));

    // 同一冻结快照改用 real-model-a（实际模型名已被覆盖为不存在的值）。
    await page.locator('.rerun').getByLabel('本次任务模型').selectOption(BAD_MODEL);
    await page.getByRole('button', { name: '用当前快照重新诊断' }).click();
    await expect(page).not.toHaveURL(new RegExp(`/diagnoses/${firstId}$`), { timeout: 60000 });
    const degradedId = page.url().split('/').filter(Boolean).pop()!;
    await waitTerminalReport(page);

    const tabs = page.getByRole('tab');
    await expect(tabs.first()).toContainText(expectedScore.toFixed(1));
    await expect(tabs.first()).toContainText('仅评分');

    // 规则评分保留；公开真实供应商错误码 MODEL_UNAVAILABLE；无报告正文。
    await expect(page.getByText(/AI 报告未生成/)).toBeVisible();
    await expect(page.locator('#job-report').getByRole('alert')).toContainText('MODEL_UNAVAILABLE');
    await expect(page.locator('.report-columns')).toHaveCount(0);

    const degraded = await apiJson(page, 'GET', `/diagnoses/${degradedId}`);
    expect(degraded.data.items[0].status).toBe('score_only');
    expect(degraded.data.items[0].model_metadata.model_id).toBe(BAD_MODEL);
    expect(degraded.data.items[0].score_result.score).toBe(expectedScore);
    const degradedJson = JSON.stringify(degraded.data);
    assertNoContactLeak(degradedJson);
    fs.writeFileSync(`${EVIDENCE_DIR}/03-diagnosis-degraded.json`, degradedJson);
    await page.screenshot({ path: `${EVIDENCE_DIR}/03-report-degraded.png`, fullPage: true });

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    expect(markdown).toContain(`- 总分：${expectedScore.toFixed(1)} / 100`);
    expect(markdown).toContain('- 结果状态：仅规则评分（AI 报告未生成）');
    expect(markdown).toContain('AI 报告未生成，本岗位已降级为仅规则评分。');
    expect(markdown).toContain('- 错误码：MODEL_UNAVAILABLE');
    expect(markdown).toContain(`- 模型选择：${BAD_MODEL}`);
    expect(markdown).toContain('- 供应商：deepseek');
    expect(markdown).toContain('- 实际模型：ai03-nonexistent-model-zzz');
  });
});
