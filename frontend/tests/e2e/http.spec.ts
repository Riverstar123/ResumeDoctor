import { test, expect, type Page } from '@playwright/test';
import profile from '../../../docs/examples/profile.json' with { type: 'json' };

const models = {
  default_model_id: 'api-a',
  items: [
    {
      id: 'api-a',
      display_name: '文件模型 A',
      provider: 'test-provider',
      capabilities: ['profile_extract', 'diagnosis_report'],
    },
    {
      id: 'api-b',
      display_name: '对话模型 B',
      provider: 'test-provider',
      capabilities: ['profile_chat', 'job_extract'],
    },
  ],
};
async function start(page: Page) {
  await page.goto('/');
  await page.getByRole('checkbox', { name: /我已阅读/ }).check();
  await page.getByRole('button', { name: /同意并开始/ }).click();
  await expect(page.getByRole('heading', { name: '从真实经历开始' })).toBeVisible();
}
test('real HTTP transport sends multipart model/key and retries 429 with the same key', async ({
  page,
}) => {
  const keys: string[] = [];
  let writes = 0;
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (body: unknown, status = 200, headers = {}) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers,
      });
    if (path.endsWith('/session')) {
      expect(req.postDataJSON()).toEqual({ consent_version: 'v1' });
      return json({
        id: '00000000-0000-4000-8000-000000000009',
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      });
    }
    if (path.endsWith('/models')) return json(models);
    if (path.endsWith('/documents')) {
      keys.push(req.headers()['idempotency-key']);
      writes++;
      expect(req.headers()['content-type']).toContain('multipart/form-data');
      expect(req.postData()).toContain('api-a');
      if (writes === 1)
        return json(
          {
            error: { code: 'RATE_LIMITED', message: '写入限流', details: {} },
            request_id: 'test-rate-limit',
          },
          429,
          { 'Retry-After': '1' },
        );
      return json({ task_id: '00000000-0000-4000-8000-000000000010' }, 202);
    }
    if (path.includes('/tasks/'))
      return json({
        id: '00000000-0000-4000-8000-000000000010',
        kind: 'document_parse',
        status: 'succeeded',
        model_id: 'api-a',
        result: {
          resource_type: 'profile',
          resource_id: profile.id,
          version: 1,
          assistant_message: null,
        },
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    if (path.endsWith('/messages')) return json({ items: [] });
    if (path.includes('/profiles/')) return json({ ...profile, confirmed: false });
    return json(
      { error: { code: 'RESOURCE_NOT_FOUND', message: '不存在' }, request_id: 'test' },
      404,
    );
  });
  await start(page);
  await expect(page.getByText('演示数据', { exact: true })).toHaveCount(0);
  await page.getByLabel('选择简历文件').setInputFiles({
    name: 'synthetic.docx',
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    buffer: Buffer.from('Synthetic multipart test only'),
  });
  await page.getByRole('button', { name: /上传并整理档案/ }).click();
  await expect(page.getByRole('alert')).toContainText('写入限流');
  await expect(page.getByRole('button', { name: /上传并整理档案/ })).toBeEnabled();
  await page.getByRole('button', { name: /上传并整理档案/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(keys[0].length).toBeGreaterThanOrEqual(16);
  await expect(page.getByLabel('本次任务模型')).toHaveValue('');
  await page.getByLabel('本次任务模型').selectOption('api-b');
});
test('404 remains a recoverable error; 401 clears session and asks for consent again', async ({
  page,
}) => {
  let status = 404;
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    let code = 200;
    if (path.endsWith('/session'))
      body = {
        id: '00000000-0000-4000-8000-000000000009',
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      };
    else if (path.endsWith('/models')) body = models;
    else {
      code = status;
      body = {
        error: {
          code: status === 401 ? 'SESSION_EXPIRED' : 'RESOURCE_NOT_FOUND',
          message: status === 401 ? '会话已过期' : '资料不存在',
        },
        request_id: 'http-error-test',
      };
    }
    return route.fulfill({
      status: code,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  await start(page);
  await page.goto('/profiles/00000000-0000-4000-8000-000000000099');
  await expect(page.getByRole('alert')).toContainText('资料不存在');
  status = 401;
  await page.getByRole('button', { name: '重新读取' }).click();
  await expect(page.getByRole('heading', { name: '你的资料，由你掌握' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('会话已过期');
});
