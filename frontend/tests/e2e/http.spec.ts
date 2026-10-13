import { test, expect, type Page } from '@playwright/test';
import profile from '../../../docs/examples/profile.json' with { type: 'json' };
import jobExample from '../../../docs/examples/job.json' with { type: 'json' };

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
test('a retried first message replays the frozen body instead of the latest version', async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const keys: string[] = [];
  const bodies: Record<string, unknown>[] = [];
  const firstBodies = new Map<string, string>();
  const readsAtSend: number[] = [];
  let profileReads = 0;
  let version = 1;
  await page.route('**/api/v1/**', (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/session'))
      return json({
        id: '00000000-0000-4000-8000-000000000009',
        expires_at: new Date(Date.now() + 86400000).toISOString(),
      });
    if (path.endsWith('/models')) return json(models);
    if (path.endsWith('/profiles') && req.method() === 'POST')
      return json({ ...profile, version, confirmed: false });
    if (path.endsWith('/messages') && req.method() === 'POST') {
      const key = req.headers()['idempotency-key'] || '';
      const body = req.postDataJSON() as Record<string, unknown>;
      keys.push(key);
      bodies.push(body);
      readsAtSend.push(profileReads);
      // docs/api/README.md「幂等与并发」：同一 key 相同 body 返回首次资源与状态码，
      // 内容不同返回 409 IDEMPOTENCY_CONFLICT。
      const first = firstBodies.get(key);
      if (first !== undefined) {
        if (first !== JSON.stringify(body))
          return json(
            { error: { code: 'IDEMPOTENCY_CONFLICT', message: '同一幂等键的请求内容不同' } },
            409,
          );
        return json({ task_id: '00000000-0000-4000-8000-000000000010' }, 202);
      }
      firstBodies.set(key, JSON.stringify(body));
      version = 2; // 服务端已受理并升版，但响应在返回途中丢失
      return route.abort('connectionfailed');
    }
    // 档案页挂载后会读取消息列表。必须按契约返回 MessageList，否则
    // messages.data.items.filter 会抛 TypeError；只断言已跳转发现不了页面崩溃。
    if (path.endsWith('/messages')) return json({ items: [] });
    if (path.includes('/profiles/')) {
      profileReads++;
      return json({ ...profile, version, confirmed: false });
    }
    if (path.includes('/tasks/'))
      return json({
        id: '00000000-0000-4000-8000-000000000010',
        kind: 'profile_chat',
        status: 'succeeded',
        model_id: 'api-b',
        result: {
          resource_type: 'profile',
          resource_id: profile.id,
          version,
          assistant_message: null,
        },
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    return json(
      { error: { code: 'RESOURCE_NOT_FOUND', message: '不存在' }, request_id: 'test' },
      404,
    );
  });
  await start(page);
  await page.getByRole('button', { name: '对话整理', exact: true }).click();
  await page.getByLabel('本次任务模型').selectOption('api-b');
  await page.getByLabel('经历描述', { exact: true }).fill('合成经历：使用 Python 整理课程数据。');
  await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  await expect(page.getByRole('alert')).toContainText('连接中断');

  // 同一输入重试：幂等键、请求体与首次完全一致，且不再重新读取最新版本
  await page.getByRole('button', { name: /发送并生成草稿/ }).click();
  await expect(page).toHaveURL(/\/profiles\//);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(bodies[0].base_version).toBe(1);
  expect(bodies[1]).toEqual(bodies[0]);
  // 第二次发送没有重新读取最新版本（否则 base_version 会变成 2）
  expect(readsAtSend).toEqual([1, 1]);
  // 成功回归还必须证明档案页真的渲染出来，而不是悄悄崩在错误边界里
  await expect(page.getByLabel('经历概述')).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('a failed job list refresh keeps the unsaved JD draft and the editor', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const jobA = {
    ...jobExample,
    id: '00000000-0000-4000-8000-0000000000a1',
    version: 1,
    confirmed: true,
  };
  const jobB = {
    ...jobExample,
    id: '00000000-0000-4000-8000-0000000000a2',
    version: 1,
    confirmed: true,
    content: { ...jobExample.content, title: '新提取岗位 B' },
  };
  const taskId = '00000000-0000-4000-8000-0000000000b1';
  let failList = false;
  // 任务保持 running，直到测试自己放行：避免"编辑"与"任务完成"之间靠时序抢跑
  let allowComplete = false;
  // 直接带着已确认档案与一个岗位进入岗位页，省去前置流程
  await page.addInitScript(
    ([profileId, jobId]) => {
      sessionStorage.setItem(
        'rd:workspace:http',
        JSON.stringify({
          session: {
            id: '00000000-0000-4000-8000-000000000009',
            expires_at: new Date(Date.now() + 86400000).toISOString(),
          },
          profileId,
          jobIds: [jobId],
          selectedJobIds: [jobId],
          diagnosisIds: [],
        }),
      );
    },
    [profile.id, jobA.id],
  );
  await page.route('**/api/v1/**', (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/models')) return json({ ...models, default_model_id: 'api-b' });
    if (path.includes('/profiles/')) return json({ ...profile, confirmed: true });
    if (path === '/api/v1/jobs' && req.method() === 'POST') {
      failList = true; // 新岗位受理后，紧接着的那次列表重载会失败
      return json({ task_id: taskId }, 202);
    }
    if (path.startsWith('/api/v1/jobs/')) {
      if (path.endsWith(jobB.id)) return json(jobB);
      if (failList)
        return json(
          {
            error: { code: 'INTERNAL_ERROR', message: '演示：岗位列表读取失败' },
            request_id: 'list-fail',
          },
          500,
        );
      return json(jobA);
    }
    if (path.includes('/tasks/')) {
      return json({
        id: taskId,
        kind: 'job_parse',
        status: allowComplete ? 'succeeded' : 'running',
        model_id: 'api-b',
        result: {
          resource_type: 'job',
          resource_id: jobB.id,
          version: 1,
          assistant_message: null,
        },
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }
    return json(
      { error: { code: 'RESOURCE_NOT_FOUND', message: '不存在' }, request_id: 'test' },
      404,
    );
  });
  await page.goto('/jobs');
  await page.getByRole('button', { name: '核对要求' }).click();
  await expect(page.locator('.job-editor h2')).toHaveText(jobA.content.title);
  await page.getByLabel('职位描述（JD）').fill('必须有 Python 项目应用经验。');
  await page.getByRole('button', { name: '提取岗位要求', exact: false }).click();
  // 任务运行期间制造未保存修改（编辑器此时仍然可编辑），确认写入后再放行任务
  await page.getByLabel('岗位名称', { exact: true }).fill('synthetic-unsaved-draft');
  await expect(page.getByLabel('岗位名称', { exact: true })).toHaveValue('synthetic-unsaved-draft');
  allowComplete = true;

  // 任务完成触发列表重载，而这次重载失败：编辑器与草稿必须都还在
  await expect(page.getByRole('alert')).toContainText('演示：岗位列表读取失败');
  await expect(page.locator('.job-editor h2')).toHaveText(jobA.content.title);
  await expect(page.getByLabel('岗位名称', { exact: true })).toHaveValue('synthetic-unsaved-draft');

  // 重试成功后草稿、编辑器与 dirty 状态保持一致
  failList = false;
  await page.getByRole('button', { name: '重新读取' }).click();
  await expect(page.locator('.job-list-item')).toHaveCount(2);
  await expect(page.locator('.job-editor h2')).toHaveText(jobA.content.title);
  await expect(page.getByLabel('岗位名称', { exact: true })).toHaveValue('synthetic-unsaved-draft');
  await expect(page.getByRole('button', { name: '跳到新岗位并放弃当前修改' })).toBeVisible();
  expect(pageErrors).toEqual([]);
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
