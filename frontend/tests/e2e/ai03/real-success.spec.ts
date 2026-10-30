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
import { JOB_TEXTS } from '../qa03db/helpers-db';
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
// 两个模型。
//
// 断言分层（A 复审第 3 项）：
// - 真实提取的事实数量/分数是*语义结果*，随供应商合法变化（实测 DeepSeek
//   对登记素材给出 4 事实，单 Python JD 得 50.0 partial），这里只做结构与
//   来源校验，不硬编码数量或黄金分；黄金分回归由 fake 的 QA-03 正式栈承担。
// - 确定性契约：同一份冻结 Profile/JD 快照切换报告模型，M4 ScoreResult 必须
//   逐岗位完全相同（分数只依赖快照，不依赖报告模型）。
test.describe('AI-03 成功路线（fake 开发 / real 验收）', () => {
  test('真 PDF 全链路，切第二模型后同快照平分、元信息不同', async ({ page }) => {
    const browserErrors: string[] = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));

    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

    await consent(page);
    const pid = await uploadPdf(page);
    const profile = await apiJson(page, 'GET', `/profiles/${pid}`);
    expect(profile.status).toBe(200);
    // 结构与来源校验：至少一条事实；每条证据有 page:N 定位与非空原文引用。
    expect(profile.data.content.facts.length).toBeGreaterThanOrEqual(1);
    const evidence = profile.data.content.evidence;
    expect(evidence.length).toBeGreaterThanOrEqual(1);
    for (const item of evidence) {
      expect(item.locator).toMatch(/^page:\d+$/);
      expect(item.quote?.trim()).toBeTruthy();
      expect(item.source_type).toBeTruthy();
    }
    await confirmProfile(page);

    for (const raw of JOB_TEXTS) await addConfirmedJob(page, raw);
    const firstId = await startDiagnosis(page);
    await waitTerminalReport(page);

    const tabs = page.getByRole('tab');
    await expect(tabs).toHaveCount(5);
    const first = await apiJson(page, 'GET', `/diagnoses/${firstId}`);
    expect(first.data.items).toHaveLength(5);
    const firstScores = scoreValues(first as never);
    // 页面展示的就是服务端返回的分数（逐岗位读，不假设具体数值）。
    for (const [index, score] of firstScores.entries()) {
      await expect(tabs.nth(index)).toContainText(score.toFixed(1));
    }
    for (const item of first.data.items) {
      expect(item.status).toBe('succeeded');
      expect(item.model_metadata.model_id).toBe(DEFAULT_MODEL);
      expect(item.model_metadata.provider).toBe(REAL ? 'deepseek' : 'fake');
    }
    const firstJson = JSON.stringify(first.data);
    assertNoContactLeak(firstJson);
    fs.writeFileSync(`${EVIDENCE_DIR}/01-diagnosis-default.json`, firstJson);
    await page.screenshot({ path: `${EVIDENCE_DIR}/01-report-default.png`, fullPage: true });

    // 正式 Markdown renderer：结构与供应商元信息；real 不得出现假模型声明。
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    expect(markdown).toContain('### 规则评分（由 M4 计算，报告不可修改）');
    expect(markdown).toContain(`- 模型选择：${DEFAULT_MODEL}`);
    expect(markdown).toContain(`- 供应商：${REAL ? 'deepseek' : 'fake'}`);
    if (REAL) {
      expect(markdown).not.toContain('演示假模型');
    } else {
      expect(markdown).toContain('注意：本报告由演示假模型生成，不代表真实诊断结论。');
    }

    // T19/T20：同一冻结快照切换第二个模型重新诊断（新建诊断，不改快照）。
    await page.locator('.rerun').getByLabel('本次任务模型').selectOption(SWITCH_MODEL);
    await page.getByRole('button', { name: '用当前快照重新诊断' }).click();
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
    expect(scoreValues(second as never)).toEqual(firstScores);
    if (REAL) {
      // real-model-b 是智谱 GLM：供应商标签与实际模型名都与默认条目不同。
      const firstActual = first.data.items[0].model_metadata.model;
      const secondActual = second.data.items[0].model_metadata.model;
      expect(firstActual).not.toBe(secondActual);
      expect(second.data.items[0].model_metadata.provider).toBe('bigmodel');
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
