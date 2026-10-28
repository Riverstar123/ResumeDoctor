import { expect, request as playwrightRequest, test } from '@playwright/test';
import { addConfirmedJob, confirmProfile, consent, startDiagnosis } from '../qa03/helpers';
import {
  chatFullProfile,
  e2eState,
  EVIDENCE_DIR,
  JOB_TEXTS,
  releaseBarrier,
  sessionToken,
  waitBlocked,
  waitIterationDone,
  waitZeroResidue,
} from './helpers-db';

// QA-03 正式栈 revoke 变体：服务端屏障让 worker 的 diagnosis_report 调用
// 确定性停在飞行中（开关只来自 worker 进程环境）。本用例回应评审意见：
// 1. 删除前保存旧会话 cookie，删除后用【独立请求上下文】重放旧 cookie，
//    断言旧令牌本身失效（401 SESSION_EXPIRED）——新建会话的 404 只是隔离检查，
//    不能证明撤销生效；
// 2. 放行并等待原后台迭代真正收尾后，在数据库侧逐表确认该会话十张表零残留，
//    即没有任务结果、档案或诊断被迟到写回。
test.describe('QA-03 正式栈 revoke 变体：T16 报告调用飞行中撤销', () => {
  test('旧 cookie 重放 401；放行原任务后数据库零写回；新会话 404 仅作隔离检查', async ({
    page,
    request,
  }) => {
    await consent(page);
    const pid = await chatFullProfile(page);
    await confirmProfile(page);
    await addConfirmedJob(page, JOB_TEXTS[0]);

    await startDiagnosis(page);
    await expect(page.getByRole('heading', { name: '正在逐个分析目标岗位' })).toBeVisible();
    const notice = page.locator('.notice', { hasText: '任务编号' });
    const match = (await notice.innerText()).match(/任务编号：([0-9a-f-]+)/);
    expect(match).not.toBeNull();
    const taskId = match![1];
    const oldDiagnosisUrl = page.url();

    // 删除前保存旧会话令牌（cookie 原值），之后不再依赖浏览器自身的 cookie 罐。
    const oldToken = await sessionToken(page);

    // 等待独立 worker 的报告调用确实进入服务端同步屏障（真飞行中，而非排队前）。
    const blocked = await waitBlocked(request, oldToken);
    const sid = blocked.session_id!;
    expect(sid).toBeTruthy();
    // 撤销前各表确有数据：之后的零残留才不是空库上的空断言。
    expect(blocked.counts).toMatchObject({
      profiles: 1,
      profile_versions: 2,
      jobs: 1,
      tasks: 3,
      diagnoses: 1,
      diagnosis_items: 1,
    });
    await page.screenshot({ path: `${EVIDENCE_DIR}/07-real-revoke-blocked.png`, fullPage: true });

    // 通过真实 UI 撤销：侧边栏入口 → <dialog> 模态确认。
    await page.getByRole('button', { name: '删除本会话资料' }).click();
    await page.getByRole('button', { name: '确认删除全部资料' }).click();
    await expect(page.getByRole('heading', { name: '你的资料，由你掌握' })).toBeVisible();

    // 评审点 1：独立请求上下文重放【旧 cookie】——不带任何新会话令牌，
    // 旧令牌必须自身失效（401），而不是靠新会话天然 404 来体现。
    const origin = new URL(page.url()).origin;
    const replay = await playwrightRequest.newContext({ baseURL: origin });
    const cookieHeader = { Cookie: `rd_session=${oldToken}` };
    const oldProfile = await replay.get(`/api/v1/profiles/${pid}`, { headers: cookieHeader });
    expect(oldProfile.status()).toBe(401);
    expect((await oldProfile.json()).error.code).toBe('SESSION_EXPIRED');
    const oldTask = await replay.get(`/api/v1/tasks/${taskId}`, { headers: cookieHeader });
    expect(oldTask.status()).toBe(401);
    expect((await oldTask.json()).error.code).toBe('SESSION_EXPIRED');
    await replay.dispose();

    // 隔离检查（保留）：另一个全新会话读不到旧资源，契约码是 404，而非 401/403。
    const fresh = await playwrightRequest.newContext({ baseURL: origin });
    await fresh.post('/api/v1/session', {
      headers: { Origin: origin },
      data: { consent_version: 'v1' },
    });
    const isolated = await fresh.get(`/api/v1/profiles/${pid}`);
    expect(isolated.status()).toBe(404);
    expect((await isolated.json()).error.code).toBe('RESOURCE_NOT_FOUND');
    await fresh.dispose();

    // 评审点 2：放行仍在飞行的原后台任务，等它在 worker 侧完成整轮收尾，
    // 再等 cleanup_expired 物理清除——十张业务表对该 sid 必须全部为 0。
    const releaseTs = Date.now() / 1000;
    await releaseBarrier(request);
    await waitIterationDone(request, oldToken, sid, taskId, releaseTs);
    const clean = await waitZeroResidue(request, oldToken, sid);
    expect(clean.session_id).toBe(sid);
    expect(clean.revoked).toBe(true);
    expect(clean.counts).toEqual({
      profiles: 0,
      profile_versions: 0,
      jobs: 0,
      job_versions: 0,
      tasks: 0,
      diagnoses: 0,
      diagnosis_items: 0,
      idempotency_keys: 0,
      messages: 0,
      documents: 0,
    });

    // 浏览器侧：重新同意后打开旧诊断链接，资源已随撤销一并失效。
    await page.getByRole('checkbox', { name: /我已阅读/ }).check();
    await page.getByRole('button', { name: /同意并开始/ }).click();
    await expect(page.getByRole('heading', { name: '从真实经历开始' })).toBeVisible();
    await page.goto(oldDiagnosisUrl);
    await expect(page.getByRole('alert')).toContainText('RESOURCE_NOT_FOUND');
    await page.screenshot({ path: `${EVIDENCE_DIR}/08-real-revoke-after.png`, fullPage: true });

    // 终态复核：控制面读数与浏览器观察一致。
    const finalState = await e2eState(request, oldToken, sid);
    expect(finalState.released).toBe(true);
    expect(Object.values(finalState.counts).every((count) => count === 0)).toBe(true);
  });
});
