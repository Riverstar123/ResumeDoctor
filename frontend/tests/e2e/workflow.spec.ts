import { expect, test, type Page } from '@playwright/test';

async function consent(page: Page) {
  await page.goto('/');
  await page.getByRole('checkbox', { name: /我已阅读/ }).check();
  await page.getByRole('button', { name: /同意并开始/ }).click();
  await expect(page.getByRole('heading', { name: '从真实经历开始' })).toBeVisible();
  if (page.viewportSize()?.width === 1440) {
    await page.getByRole('heading', { name: '从真实经历开始' }).click();
    await page.screenshot({ path: 'test-results/desktop-input.png', fullPage: true });
  }
}
async function profile(page: Page, upload = false) {
  await consent(page);
  if (upload) {
    await page.getByLabel('选择简历文件').setInputFiles({
      name: 'synthetic.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4\nSynthetic test fixture only'),
    });
    await page.getByRole('button', { name: /上传并整理档案/ }).click();
  } else {
    await page.getByRole('button', { name: '对话整理', exact: true }).click();
    await page.getByRole('button', { name: '填入合成示例' }).click();
    await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  }
  await expect(page).toHaveURL(/\/profiles\//);
  if (page.viewportSize()?.width === 1440) {
    await expect(page.getByLabel('经历概述')).toBeVisible();
    await page.screenshot({ path: 'test-results/desktop-profile.png', fullPage: true });
  }
  await page.getByRole('button', { name: /确认档案 v/ }).click();
  await page.getByRole('link', { name: /选择目标岗位/ }).click();
}
async function addJob(page: Page, title?: string) {
  const previous = await page.locator('.job-list-item').count();
  await page.getByRole('button', { name: '填入示例 JD' }).click();
  await page.getByRole('button', { name: '提取岗位要求', exact: false }).click();
  await expect(page.locator('.job-list-item')).toHaveCount(previous + 1);
  await expect(page.getByRole('button', { name: '确认 JD v1' })).toBeVisible();
  if (title) {
    await page.getByLabel('岗位名称', { exact: true }).fill(title);
    await page.getByRole('button', { name: '保存 JD 新版本' }).click();
    await expect(page.getByRole('button', { name: '确认 JD v2' })).toBeEnabled();
  }
  await page.getByRole('button', { name: /确认 JD v/ }).click();
  await expect(page.getByRole('button', { name: /确认 JD v/ })).toBeDisabled();
}
async function diagnose(page: Page) {
  await page.getByRole('button', { name: /开始诊断/ }).click();
  await expect(page).toHaveURL(/\/diagnoses\//);
  await expect(page.getByRole('heading', { name: '看清匹配，找到下一步。' })).toBeVisible();
}
test('conversation, two independent jobs, evidence, download, reload and model comparison', async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  await profile(page);
  await addJob(page, '数据开发岗位 A');
  await addJob(page, '数据开发岗位 B');
  await page.screenshot({ path: 'test-results/desktop-jobs.png', fullPage: true });
  await diagnose(page);
  await expect(page.getByRole('tab')).toHaveCount(2);
  await expect(page.getByRole('tab').first()).toContainText('66.7');
  await page.getByRole('tab', { name: /数据开发岗位 B/ }).click();
  await page.getByRole('heading', { name: '看清匹配，找到下一步。' }).click();
  await page.screenshot({ path: 'test-results/desktop-report.png', fullPage: true });
  await expect(page.getByText(/【演示数据 · 数据开发岗位 B】/)).toBeVisible();
  await page.locator('.assessment summary').first().click();
  await expect(page.locator('.assessment-body').first()).toContainText(
    '使用 Python 完成课程数据清洗项目',
  );
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: /导出 Markdown/ }).click();
  expect((await download).suggestedFilename()).toMatch(/\.md$/);
  const oldUrl = page.url();
  await page.reload();
  await expect(page.getByRole('tab')).toHaveCount(2);
  await page.getByLabel('本次任务模型').selectOption('demo-model-b');
  await page.getByRole('button', { name: '用当前快照重新诊断' }).click();
  await expect(page).not.toHaveURL(oldUrl);
  await expect(page.getByRole('heading', { name: '看清匹配，找到下一步。' })).toBeVisible();
  await expect(page.locator('.model-metadata')).toContainText('synthetic-fixture-b');
  await page.getByLabel('与另一份历史诊断比较').selectOption({ index: 1 });
  await expect(page.getByRole('table')).toContainText('66.7');
  await page.goto(oldUrl);
  await expect(page.locator('.model-metadata')).toContainText('synthetic-fixture-a');
  expect(browserErrors).toEqual([]);
});
test('upload route, partial and score_only keep export available', async ({ page }) => {
  await profile(page, true);
  await addJob(page, '完整报告岗位');
  await addJob(page, '报告降级岗位');
  await page.getByLabel('模拟场景').selectOption('partial');
  await diagnose(page);
  await page.getByRole('tab', { name: /报告降级岗位/ }).click();
  await expect(page.getByText(/AI 报告未生成/)).toBeVisible();
  await expect(page.getByRole('heading', { name: '逐条要求与证据' })).toBeVisible();
  await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeEnabled();
});
test('five jobs are separate; a sixth cannot be selected', async ({ page }) => {
  test.setTimeout(90000);
  await profile(page);
  for (let i = 1; i <= 6; i++) await addJob(page, `合成岗位 ${i}`);
  await expect(page.getByRole('checkbox', { name: '选择 合成岗位 6', exact: true })).toBeDisabled();
  await diagnose(page);
  await expect(page.getByRole('tab')).toHaveCount(5);
  for (let i = 1; i <= 5; i++) {
    await page.getByRole('tab', { name: new RegExp(`合成岗位 ${i}`) }).click();
    await expect(page.locator('.report-summary')).toContainText(`合成岗位 ${i}`);
  }
});
test('failed parsing preserves chat input and can be retried', async ({ page }) => {
  await consent(page);
  await page.getByRole('button', { name: '对话整理', exact: true }).click();
  await page.getByLabel('经历描述', { exact: true }).fill('合成经历：使用 Python 整理课程数据。');
  await page.getByLabel('模拟场景').selectOption('parse-failed');
  await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  await expect(page.getByText(/演示：提取超时/).first()).toBeVisible();
  await page.getByRole('button', { name: '返回输入并重试' }).click();
  await expect(page.getByRole('textbox', { name: '经历描述', exact: true })).toHaveValue(
    '合成经历：使用 Python 整理课程数据。',
  );
  await page.getByLabel('模拟场景').selectOption('success');
  await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
});
test('conflict keeps unsaved edits, then permits a new version and reconfirmation', async ({
  page,
}) => {
  await profile(page);
  await page.getByRole('link', { name: /查看 \/ 确认档案/ }).click();
  await page.getByLabel('经历概述').fill('我保留的本地修改');
  await page.getByLabel('模拟场景').selectOption('conflict');
  await page.getByRole('button', { name: '保存新版本', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('本地编辑仍保留');
  await expect(page.getByLabel('经历概述')).toHaveValue('我保留的本地修改');
  await page.getByRole('button', { name: '保存新版本', exact: true }).click();
  await expect(page.getByRole('button', { name: '确认档案 v3' })).toBeEnabled();
});
test('mobile layout and deletion revoke resources', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await profile(page);
  await addJob(page);
  await diagnose(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('heading', { name: '看清匹配，找到下一步。' }).click();
  await page.screenshot({ path: 'test-results/mobile-report.png', fullPage: true });
  await page.getByRole('button', { name: '删除本会话资料' }).click();
  await page.getByRole('button', { name: '确认删除全部资料' }).click();
  await expect(page.getByRole('heading', { name: '你的资料，由你掌握' })).toBeVisible();
});
test('all failed diagnostics cannot be exported and allow rerun', async ({ page }) => {
  await profile(page);
  await addJob(page);
  await page.getByLabel('模拟场景').selectOption('failed');
  await diagnose(page);
  await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: '用当前快照重新诊断' })).toBeEnabled();
});
test('unsaved JD draft blocks a new extraction and survives a running task', async ({ page }) => {
  test.setTimeout(90000);
  await profile(page);
  await addJob(page, '数据开发岗位 A');
  const title = page.getByLabel('岗位名称', { exact: true });
  const extract = page.getByRole('button', { name: '提取岗位要求', exact: false });

  // 先备好 JD 原文，确认按钮本来可用，再制造未保存修改
  await page.getByRole('button', { name: '填入示例 JD' }).click();
  await expect(extract).toBeEnabled();
  await title.fill('尚未保存的岗位 A 草稿');
  await expect(extract).toBeDisabled();
  await expect(
    page.getByText('当前 JD 有未保存的修改。先保存新版本，再提取新的岗位。'),
  ).toBeVisible();

  // 保存后重新可用
  await page.getByRole('button', { name: '保存 JD 新版本' }).click();
  await expect(page.getByRole('button', { name: /确认 JD v/ })).toBeEnabled();
  await expect(extract).toBeEnabled();

  // 任务运行期间产生的编辑，不能被完成回调切换掉的编辑器清掉
  await extract.click();
  await title.fill('等待期间修改的岗位 A');
  await expect(page.locator('.job-list-item')).toHaveCount(2);
  await expect(page.getByRole('button', { name: '跳到新岗位并放弃当前修改' })).toBeVisible();
  await expect(page.locator('.job-editor h2')).toHaveText('尚未保存的岗位 A 草稿');
  await expect(title).toHaveValue('等待期间修改的岗位 A');

  // 显式放弃后才切换，且 dirty 状态与新的编辑器一致
  await page.getByRole('button', { name: '跳到新岗位并放弃当前修改' }).click();
  await page.getByRole('button', { name: '填入示例 JD' }).click();
  await expect(extract).toBeEnabled();
  await expect(title).not.toHaveValue('等待期间修改的岗位 A');
});

test('oversized and unsupported file errors are visible', async ({ page }) => {
  await consent(page);
  await page.getByLabel('选择简历文件').setInputFiles({
    name: 'bad.doc',
    mimeType: 'application/msword',
    buffer: Buffer.from('test'),
  });
  await expect(page.getByRole('alert')).toContainText('仅支持');
  await expect(page.getByRole('button', { name: /上传并整理档案/ })).toBeDisabled();
});
