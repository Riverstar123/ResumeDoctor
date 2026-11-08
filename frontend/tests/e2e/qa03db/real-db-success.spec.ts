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
import {
  EVIDENCE_DIR,
  GOLDEN_SCORES,
  JOB_FULL,
  JOB_TEXTS,
  PROFILE_FULL,
  sendProfileSupplement,
  uploadReal,
} from './helpers-db';

// QA-03 正式栈（app.database + 独立 worker + 临时 PostgreSQL）成功路线：
// 真实文件解析、确定性评分、ReportService 校验/导出与持久化，模型仅替换为 fake。
test.describe('QA-03 正式栈 success 变体', () => {
  test('真 PDF 上传、五岗位黄金分、正式 Markdown renderer、刷新持久化、切模型分数不变', async ({
    page,
  }) => {
    const browserErrors: string[] = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));

    await consent(page);
    const pid = await uploadReal(page, 'synthetic-resume.pdf');

    // M3 真实 PDF 解析：三条事实与 page:1/2/3 定位（不是 SyntheticIntake 的固定返回）。
    const profile = await apiJson(page, 'GET', `/profiles/${pid}`);
    expect(profile.data.content.facts).toHaveLength(3);
    expect(profile.data.content.evidence.map((e: { locator: string | null }) => e.locator)).toEqual(
      ['page:1', 'page:2', 'page:3'],
    );
    await confirmProfile(page);

    for (const raw of JOB_TEXTS) await addConfirmedJob(page, raw);
    await startDiagnosis(page);
    await waitTerminalReport(page);

    const tabs = page.getByRole('tab');
    await expect(tabs).toHaveCount(5);
    // INT-02 实测基准：66.7 / 0 / 100 / 50 / 0，每个 JD 独立评分依据。
    for (const [index, score] of GOLDEN_SCORES.entries()) {
      await expect(tabs.nth(index)).toContainText(score);
    }

    await page.screenshot({ path: `${EVIDENCE_DIR}/05-real-golden-report.png`, fullPage: true });

    // 正式 Markdown renderer（app/reporting/markdown.py），非轻量栈的 FakeReporting。
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const download = await downloadPromise;
    const markdown = fs.readFileSync((await download.path())!, 'utf8');
    expect(markdown).toContain('### 规则评分（由 M4 计算，报告不可修改）');
    expect(markdown).toContain('- 总分：66.7 / 100');
    expect(markdown).toContain('- 结果状态：完成');
    expect(markdown).toContain('### 模型与版本');
    expect(markdown).toContain('- 供应商：fake');
    expect(markdown).toContain('注意：本报告由演示假模型生成，不代表真实诊断结论。');

    // PostgreSQL 持久化：整页刷新后同报告、同分数仍可读（不经任何内存替身）。
    await page.reload();
    await waitTerminalReport(page);
    await expect(page.getByRole('tab').nth(0)).toContainText('66.7');

    // T19/T20：同冻结快照换 demo-model-b 重诊，分数不变、元数据更新、旧报告不改写。
    const firstUrl = page.url();
    await page.locator('.rerun').getByLabel('本次任务模型').selectOption('demo-model-b');
    await page.getByRole('button', { name: '用同一份材料再算一次' }).click();
    await waitTerminalReport(page);
    await expect(page.getByRole('tab').nth(0)).toContainText('66.7');
    await expect(page.locator('.model-metadata')).toContainText('demo-model-b');
    await page.goto(firstUrl);
    await waitTerminalReport(page);
    await expect(page.locator('.model-metadata')).toContainText('demo-model-a');
    expect(browserErrors).toEqual([]);
  });

  test('真 DOCX 上传显示分页未核验提示，确认后正常评分', async ({ page }) => {
    await consent(page);
    await uploadReal(page, 'synthetic-resume.docx');
    const warning = page.locator('section.notice.task-warnings').first();
    await expect(warning).toBeVisible();
    await expect(warning).toContainText('分页');
    await expect(warning.locator('code.warning-code')).toHaveText('DOCX_PAGINATION_UNVERIFIED');

    await confirmProfile(page);
    await addConfirmedJob(page, JOB_FULL);
    await startDiagnosis(page);
    await waitTerminalReport(page);
    await expect(page.getByRole('tab').first()).toContainText('66.7');
    await page.screenshot({ path: `${EVIDENCE_DIR}/06-real-docx-warning.png`, fullPage: true });
  });

  test('对话两轮建档（v1→v2→v3），单 Python JD 得 100 分', async ({ page }) => {
    await consent(page);
    // 首条只给第一行登记素材 → v2 一个事实；再补充完整素材 → v3 三个事实。
    await page.getByRole('button', { name: '对话整理', exact: true }).click();
    await page.getByLabel('经历描述', { exact: true }).fill(PROFILE_FULL.split('\n')[0]);
    await page.getByRole('button', { name: /发送并生成草稿/ }).click();
    await expect(page).toHaveURL(/\/profiles\//);
    await expect(page.getByRole('button', { name: '确认档案 v2' })).toBeVisible();

    await sendProfileSupplement(page, PROFILE_FULL);
    await expect(page.getByRole('button', { name: '确认档案 v3' })).toBeEnabled();

    const profileId = page.url().split('/').filter(Boolean).pop()!;
    const profile = await apiJson(page, 'GET', `/profiles/${profileId}`);
    expect(profile.data.content.facts).toHaveLength(3);
    await page.getByRole('button', { name: '确认档案 v3' }).click();
    await page.getByRole('link', { name: /选择目标岗位/ }).click();

    await addConfirmedJob(page, JOB_TEXTS[2]); // 单行「必须有 Python 项目应用经验。」→ 100
    await startDiagnosis(page);
    await waitTerminalReport(page);
    await expect(page.getByRole('tab').first()).toContainText('100.0');

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /导出 Markdown/ }).click();
    const markdown = fs.readFileSync((await (await downloadPromise).path())!, 'utf8');
    expect(markdown).toContain('- 总分：100.0 / 100');
  });
});
