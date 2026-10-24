/**
 * QA-02 UI boundary checks in a real browser, with mocked HTTP API responses.
 * These prove rendering/error behaviour only: not server authorization, real
 * model resistance, document parsing, backend Markdown sanitization or PG isolation.
 */
import { expect, test, type Page } from '@playwright/test';
import diagnosisItemExample from '../../../docs/examples/diagnosis-item.json' with { type: 'json' };
import jobExample from '../../../docs/examples/job.json' with { type: 'json' };
import profileExample from '../../../docs/examples/profile.json' with { type: 'json' };
import type { Diagnosis, DiagnosisItem, Job, Profile } from '../../src/types';

const OWN_ID = '00000000-0000-4000-8000-000000002510';
const FOREIGN_ID = '00000000-0000-4000-8000-000000002599';
const PROBE_ORIGIN = 'https://qa-security-exfiltration.invalid';
const PAYLOAD =
  `<img src="${PROBE_ORIGIN}/pixel" onerror="window.qaSecurityExecuted++">` +
  '<script>window.qaSecurityExecuted++</script>' +
  '<svg onload="window.qaSecurityExecuted++"></svg>' +
  '[伪装链接](javascript:window.qaSecurityExecuted++)';

function fixtures(malicious: boolean) {
  const profile = structuredClone(profileExample) as Profile;
  const job = structuredClone(jobExample) as Job;
  const item = structuredClone(diagnosisItemExample) as DiagnosisItem;
  if (malicious) {
    profile.content.evidence[0].quote = `证据原文：${PAYLOAD}`;
    job.content.title = `岗位名称：${PAYLOAD}`;
    job.content.requirements[0].quote = `JD 要求：${PAYLOAD}`;
    item.score_result!.assessments[0].reason = `匹配说明：${PAYLOAD}`;
    item.report!.summary = `模型摘要：${PAYLOAD}`;
    item.report!.gaps[0].description = `差距说明：${PAYLOAD}`;
    item.report!.suggestions[0].original = `改写原文：${PAYLOAD}`;
    item.report!.suggestions[0].revised = `建议表达：${PAYLOAD}`;
    item.report!.actions[0].task = `行动建议：${PAYLOAD}`;
  }
  const diagnosis: Diagnosis = {
    id: OWN_ID,
    task_id: '00000000-0000-4000-8000-000000002511',
    status: 'succeeded',
    profile: { id: profile.id, version: profile.version },
    model_id: item.model_metadata!.model_id,
    items: [item],
    created_at: '2026-10-24T00:00:00Z',
  };
  return { profile, job, diagnosis };
}

async function mockApi(page: Page, data: ReturnType<typeof fixtures>) {
  const unexpected: string[] = [];
  const reads: string[] = [];
  await page.addInitScript(
    ({ profileId, jobId, diagnosisId }) => {
      sessionStorage.setItem(
        'rd:workspace:http',
        JSON.stringify({
          session: {
            id: '00000000-0000-4000-8000-000000002512',
            expires_at: '2099-01-01T00:00:00Z',
          },
          profileId,
          jobIds: [jobId],
          selectedJobIds: [jobId],
          diagnosisIds: [diagnosisId],
        }),
      );
      Object.assign(window, { qaSecurityExecuted: 0 });
    },
    { profileId: data.profile.id, jobId: data.job.id, diagnosisId: data.diagnosis.id },
  );
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    reads.push(path);
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (request.method() !== 'GET') {
      unexpected.push(`${request.method()} ${path}`);
      return json({ error: { code: 'TEST_UNEXPECTED_WRITE', message: '测试未授权写入' } }, 500);
    }
    if (path === '/api/v1/models')
      return json({
        default_model_id: data.diagnosis.model_id,
        items: [
          {
            id: data.diagnosis.model_id,
            display_name: '合成安全验收模型',
            provider: 'fake',
            capabilities: ['diagnosis_report'],
          },
        ],
      });
    if (path === `/api/v1/diagnoses/${OWN_ID}`) return json(data.diagnosis);
    if (path === `/api/v1/profiles/${data.profile.id}`) return json(data.profile);
    if (path === `/api/v1/jobs/${data.job.id}`) return json(data.job);
    if (path === `/api/v1/diagnoses/${FOREIGN_ID}`)
      return json(
        {
          error: { code: 'RESOURCE_NOT_FOUND', message: '资料不存在', details: {} },
          request_id: 'qa-security-synthetic-404',
        },
        404,
      );
    unexpected.push(path);
    return json({ error: { code: 'TEST_UNEXPECTED_READ', message: '测试未定义的接口' } }, 500);
  });
  return { unexpected, reads };
}

test('mock API: malicious report, evidence and JD remain text without script/image execution', async ({
  page,
}) => {
  const data = fixtures(true);
  const { unexpected } = await mockApi(page, data);
  const pageErrors: string[] = [];
  const externalRequests: string[] = [];
  const dialogs: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('dialog', async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  // A broken renderer would attempt this request; block it before any network I/O.
  await page.route(`${PROBE_ORIGIN}/**`, (route) => {
    externalRequests.push(route.request().url());
    return route.abort('blockedbyclient');
  });
  await page.goto(`/diagnoses/${OWN_ID}`);
  await expect(page.locator('.report-summary')).toHaveText(`模型摘要：${PAYLOAD}`);
  await expect(page.locator('.score-card h2')).toHaveText(`岗位名称：${PAYLOAD}`);
  await expect(page.locator('.assessment-title strong').first()).toHaveText(`JD 要求：${PAYLOAD}`);
  await page.locator('.assessment summary').first().click();
  await expect(page.locator('.assessment-body').first()).toContainText(`匹配说明：${PAYLOAD}`);
  await expect(page.locator('.assessment-body blockquote p').first()).toHaveText(
    `证据原文：${PAYLOAD}`,
  );
  await expect(page.locator('.suggestion .revised p')).toHaveText(`建议表达：${PAYLOAD}`);
  await expect(page.locator('.gap h3').first()).toHaveText(`差距说明：${PAYLOAD}`);
  await expect(page.locator('.action-item h3')).toHaveText(`行动建议：${PAYLOAD}`);
  await expect(
    page.locator('#main-content img, #main-content svg, #main-content script'),
  ).toHaveCount(0);
  await expect(page.locator('#main-content a[href^="javascript:"]')).toHaveCount(0);
  // Let two rendered frames complete so load/onerror callbacks would have a chance to fire.
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  );
  expect(await page.evaluate(() => Reflect.get(window, 'qaSecurityExecuted'))).toBe(0);
  expect(externalRequests).toEqual([]);
  expect(dialogs).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(unexpected).toEqual([]);
});

test('mock API: ordinary report and exact evidence remain readable after reload', async ({
  page,
}) => {
  const data = fixtures(false);
  const { unexpected } = await mockApi(page, data);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`/diagnoses/${OWN_ID}`);
  await expect(page.locator('.report-summary')).toHaveText(data.diagnosis.items[0].report!.summary);
  await expect(page.locator('.score-number')).toContainText('66.7');
  await expect(page.locator('.score-card h2')).toHaveText(data.job.content.title);
  await page.locator('.assessment summary').first().click();
  await expect(page.locator('.assessment-body blockquote p').first()).toHaveText(
    data.profile.content.evidence[0].quote,
  );
  await page.reload();
  await expect(page.locator('.report-summary')).toHaveText(data.diagnosis.items[0].report!.summary);
  await expect(page.getByRole('button', { name: /导出 Markdown/ })).toBeEnabled();
  expect(pageErrors).toEqual([]);
  expect(unexpected).toEqual([]);
});

test('mock API: a foreign-resource 404 clears the previous report without demo fallback', async ({
  page,
}) => {
  // The server response is deliberately mocked: this cannot prove backend isolation.
  const data = fixtures(false);
  const { unexpected, reads } = await mockApi(page, data);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`/diagnoses/${OWN_ID}`);
  await expect(page.locator('.report-summary')).toHaveText(data.diagnosis.items[0].report!.summary);
  // Keep the same SPA/document to exercise cleanup of the already displayed report.
  await page.evaluate((id) => {
    history.pushState(null, '', `/diagnoses/${id}`);
    dispatchEvent(new PopStateEvent('popstate'));
  }, FOREIGN_ID);
  await expect(page.getByRole('alert')).toContainText('RESOURCE_NOT_FOUND');
  await expect(page.getByRole('alert')).toContainText('资料不存在');
  await expect(page.locator('.report-summary, .score-card, .suggestion')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /导出 Markdown/ })).toHaveCount(0);
  await expect(page.getByText(data.profile.content.evidence[0].quote, { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole('button', { name: '重新读取' }).click();
  await expect(page.getByRole('alert')).toContainText('RESOURCE_NOT_FOUND');
  expect(reads.filter((path) => path.endsWith(FOREIGN_ID)).length).toBeGreaterThanOrEqual(2);
  expect(pageErrors).toEqual([]);
  expect(unexpected).toEqual([]);
});
