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
import { GOLDEN_SCORES, JOB_TEXTS } from '../qa03db/helpers-db';
import {
  DEFAULT_MODEL,
  EVIDENCE_DIR,
  REAL,
  SWITCH_MODEL,
  assertNoContactLeak,
  scoreValues,
  uploadPdf,
} from './helpers-ai03';

// AI-03 T22：网页真实完成简历/JD 提取与报告生成，并在同一冻结快照上切换
// 两个模型：M4 评分逐岗位不变，模型元信息（model_id / 实际模型）随之不同。
test.describe('AI-03 成功路线（fake 开发 / real 验收）', () => {
  test('真 PDF 全链路五岗位评分，切第二模型后同快照平分、元信息不同', async ({ page }) => {
    const browserErrors: string[] = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));

    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

    await consent(page);
    const pid = await uploadPdf(page);
    const profile = await apiJson(page, 'GET', `/profiles/${pid}`);
    expect(profile.data.content.facts).toHaveLength(3);
    expect(profile.data.content.evidence.map((e: { locator: string | null }) => e.locator)).toEqual(
      ['page:1', 'page:2', 'page:3'],
    );
    await confirmProfile(page);

    for (const raw of JOB_TEXTS) await addConfirmedJob(page, raw);
    const firstId = await startDiagnosis(page);
    await waitTerminalReport(page);

    const tabs = page.getByRole('tab');
    await expect(tabs).toHaveCount(5);
    for (const [index, score] of GOLDEN_SCORES.entries()) {
      await expect(tabs.nth(index)).toContainText(score);
    }

    const first = await apiJson(page, 'GET', `/diagnoses/${firstId}`);
    expect(first.status).toBe(200);
    expect(first.data.items).toHaveLength(5);
    for (const item of first.data.items) {
      expect(item.status).toBe('succeeded');
      expect(item.model_metadata.model_id).toBe(DEFAULT_MODEL);
      expect(item.model_metadata.provider).toBe(REAL ? 'openai_compatible' : 'fake');
    }
    const firstJson = JSON.stringify(first.data);
    assertNoContactLeak(firstJson);
    fs.writeFileSync(`${EVIDENCE_DIR}/01-diagnosis-default.json`, firstJson);
    await page.screenshot({ path: `${EVIDENCE_DIR}/01-report-default.png`, fullPage: true });

    // 正式 Markdown renderer：real 模式元信息为真实供应商，且不得出现假模型声明。
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    expect(markdown).toContain('### 规则评分（由 M4 计算，报告不可修改）');
    expect(markdown).toContain(`- 模型选择：${DEFAULT_MODEL}`);
    expect(markdown).toContain(`- 供应商：${REAL ? 'openai_compatible' : 'fake'}`);
    if (REAL) {
      expect(markdown).not.toContain('演示假模型');
    } else {
      expect(markdown).toContain('注意：本报告由演示假模型生成，不代表真实诊断结论。');
    }

    // T19/T20：同一冻结快照切换第二个模型重新诊断。
    await page.locator('.rerun').getByLabel('本次任务模型').selectOption(SWITCH_MODEL);
    await page.getByRole('button', { name: '用当前快照重新诊断' }).click();
    // toHaveURL(/\/diagnoses\//) 在旧 URL 上也成立；必须显式等待离开旧诊断。
    await expect(page).not.toHaveURL(new RegExp(`/diagnoses/${firstId}$`), { timeout: 60000 });
    const secondId = page.url().split('/').filter(Boolean).pop()!;
    expect(secondId).not.toBe(firstId);
    await waitTerminalReport(page);

    const second = await apiJson(page, 'GET', `/diagnoses/${secondId}`);
    for (const item of second.data.items) {
      expect(item.status).toBe('succeeded');
      expect(item.model_metadata.model_id).toBe(SWITCH_MODEL);
    }
    // 关键验收点：分数由冻结快照与 M4 决定，换报告模型逐岗位完全相同。
    expect(scoreValues(second as never)).toEqual(scoreValues(first as never));
    if (REAL) {
      // 两个可选条目必须指向不同的实际模型名（组长配置 LLM_MODEL / LLM_MODEL_B）。
      const firstActual = first.data.items[0].model_metadata.model;
      const secondActual = second.data.items[0].model_metadata.model;
      expect(firstActual).not.toBe(secondActual);
      expect(secondActual).toBeTruthy();
    }
    const secondJson = JSON.stringify(second.data);
    assertNoContactLeak(secondJson);
    fs.writeFileSync(`${EVIDENCE_DIR}/02-diagnosis-model-switch.json`, secondJson);
    await page.screenshot({ path: `${EVIDENCE_DIR}/02-report-model-switch.png`, fullPage: true });

    // 切换不影响旧诊断：旧 URL 的元信息仍为默认模型。
    const oldAgain = await apiJson(page, 'GET', `/diagnoses/${firstId}`);
    expect(oldAgain.data.items[0].model_metadata.model_id).toBe(DEFAULT_MODEL);
    await expect(page.locator('.model-metadata').first()).toContainText(SWITCH_MODEL);

    expect(browserErrors).toEqual([]);
  });
});
