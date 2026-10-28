import { expect, test } from '@playwright/test';
import {
  addConfirmedJob,
  apiJson,
  chatProfile,
  confirmProfile,
  consent,
  EVIDENCE_DIR,
  JOB1,
  startDiagnosis,
} from './helpers';

// slow 变体：diagnosis 总入口确定性延迟 12 秒，制造「任务运行中删除会话」窗口。
// 撤销会话会取消后台任务并使旧链接/旧任务在新会话中 404（T16；同时覆盖 T15 的 UI 侧）。
test.describe('QA-03 slow 变体：T16 运行中删除会话', () => {
  test('任务运行中删除全部资料：回到同意页，旧诊断与旧任务在新会话中均 404', async ({ page }) => {
    test.setTimeout(60000);
    await consent(page);
    await chatProfile(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB1);

    await startDiagnosis(page);
    // 12 秒注入窗口内，页面必须保持非终态展示而不是提前给结论。
    await expect(page.getByRole('heading', { name: '正在逐个分析目标岗位' })).toBeVisible();
    const notice = page.locator('.notice', { hasText: '任务编号' });
    const match = (await notice.innerText()).match(/任务编号：([0-9a-f-]+)/);
    expect(match).not.toBeNull();
    const oldTaskId = match![1];
    const oldDiagnosisUrl = page.url();

    await page.screenshot({ path: `${EVIDENCE_DIR}/04-running-task.png`, fullPage: true });

    // 运行中删除：侧边栏入口 → <dialog> 模态确认。
    await page.getByRole('button', { name: '删除本会话资料' }).click();
    await page.getByRole('button', { name: '确认删除全部资料' }).click();
    await expect(page.getByRole('heading', { name: '你的资料，由你掌握' })).toBeVisible();

    // 新会话同意后打开旧诊断链接：资源已随撤销一并失效。
    await page.getByRole('checkbox', { name: /我已阅读/ }).check();
    await page.getByRole('button', { name: /同意并开始/ }).click();
    await expect(page.getByRole('heading', { name: '从真实经历开始' })).toBeVisible();
    await page.goto(oldDiagnosisUrl);
    await expect(page.getByRole('alert')).toContainText('RESOURCE_NOT_FOUND');

    const oldTask = await apiJson(page, 'GET', `/tasks/${oldTaskId}`);
    expect(oldTask.status).toBe(404);
    expect(oldTask.data.error.code).toBe('RESOURCE_NOT_FOUND');
  });
});
