import { expect, test } from '@playwright/test';
import {
  addConfirmedJob,
  chatProfile,
  confirmProfile,
  consent,
  EVIDENCE_DIR,
  JOB1,
  startDiagnosis,
  waitTerminalReport,
} from './helpers';

// fail 变体：服务端在 diagnosis 任务开始前确定性注入 PROVIDER_UNAVAILABLE，
// 没有任何评分产出 → 任务 failed、导出禁用、允许同快照重试。
test.describe('QA-03 fail 变体：诊断全部失败', () => {
  test('failed 诊断不可导出，展示错误码并允许重新诊断', async ({ page }) => {
    await consent(page);
    await chatProfile(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB1);
    await startDiagnosis(page);
    await waitTerminalReport(page);

    await expect(page.getByRole('heading', { name: '看清匹配，找到下一步。' })).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: '本次诊断没有可用评分' })).toBeVisible();
    await expect(page.getByRole('tab').first()).toContainText('处理失败');
    await expect(page.locator('#job-report').getByRole('alert')).toContainText(
      'PROVIDER_UNAVAILABLE',
    );

    await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeDisabled();
    await expect(page.getByRole('button', { name: '用同一份材料再算一次' })).toBeEnabled();

    await page.screenshot({ path: `${EVIDENCE_DIR}/03-all-failed.png`, fullPage: true });
  });
});
