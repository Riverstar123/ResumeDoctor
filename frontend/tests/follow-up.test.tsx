import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/client';
import { FollowUpWorkspace } from '../src/pages/FollowUpPage';
import type { Diagnosis, DiagnosisItem, Job, Profile, Schema, Task } from '../src/types';
import profileFixture from '../../docs/examples/profile.json';
import jobFixture from '../../docs/examples/job.json';
import itemFixture from '../../docs/examples/diagnosis-item.json';

const app = vi.hoisted(() => ({
  modelId: 'demo-model-a',
  models: [
    {
      id: 'demo-model-a',
      capabilities: ['profile_chat', 'diagnosis_report'],
      display_name: '演示模型',
      provider: 'fake',
    },
  ],
  workspace: { diagnosisIds: [] as string[] },
  patch: vi.fn(),
  setModelId: vi.fn(),
}));
vi.mock('../src/state', () => ({ useApp: () => app }));
const profile = { ...structuredClone(profileFixture), confirmed: true } as Profile;
const job = structuredClone(jobFixture) as Job;
const item = structuredClone(itemFixture) as DiagnosisItem;
const diagnosis: Diagnosis = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  task_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  status: 'succeeded',
  profile: { id: profile.id, version: profile.version },
  model_id: 'demo-model-a',
  items: [item],
  created_at: profile.created_at,
};
const focus: Schema['DiagnosisFocus'] = {
  diagnosis_id: diagnosis.id,
  item_id: item.id,
  requirement_id: 'r2',
};
function task(id: string, next: Profile, questionsOnly: boolean, target = focus): Task {
  return {
    id,
    kind: 'profile_chat',
    status: 'succeeded',
    model_id: app.modelId,
    created_at: profile.created_at,
    updated_at: profile.created_at,
    error: null,
    result: {
      resource_type: 'profile',
      resource_id: next.id,
      version: next.version,
      assistant_message: '你在 SQL 项目中实际负责了什么？',
      diagnosis_focus: target,
      questions_only: questionsOnly,
    },
  };
}
function Location() {
  const [params, setParams] = useSearchParams();
  return (
    <>
      <output aria-label="当前地址">
        {useLocation().pathname}
        {useLocation().search}
      </output>
      <button
        onClick={() => {
          const next = new URLSearchParams(params);
          next.delete('task');
          setParams(next);
        }}
      >
        模拟返回无任务页面
      </button>
    </>
  );
}
function page(taskId = '', initialProfile = profile) {
  return render(
    <MemoryRouter
      initialEntries={[
        `/follow-up?diagnosis=${diagnosis.id}&item=${item.id}&requirement=r2${taskId ? `&task=${taskId}` : ''}`,
      ]}
    >
      <FollowUpWorkspace
        context={{ diagnosis, item, job, profile: initialProfile }}
        focus={focus}
      />
      <Location />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  app.patch.mockClear();
  vi.spyOn(api, 'profile').mockResolvedValue(structuredClone(profile));
});

describe('job-directed follow-up', () => {
  it('starts with questions only, keeps the confirmed version, and preserves focus when recovering a task', async () => {
    vi.spyOn(api, 'sendMessage').mockResolvedValue({ task_id: 'question-task' });
    vi.spyOn(api, 'task').mockResolvedValue(task('question-task', profile, true));
    const save = vi.spyOn(api, 'saveProfile');
    const confirm = vi.spyOn(api, 'confirmProfile');
    page();
    fireEvent.click(screen.getByRole('button', { name: '生成岗位定向问题' }));
    await screen.findByText('你在 SQL 项目中实际负责了什么？');
    expect(api.sendMessage).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({
        diagnosis_focus: focus,
        questions_only: true,
        base_version: profile.version,
      }),
      expect.any(String),
    );
    expect(screen.getByLabelText('当前地址')).toHaveTextContent(`diagnosis=${diagnosis.id}`);
    expect(screen.getByLabelText('当前地址')).toHaveTextContent('task=question-task');
    expect(screen.getByRole('button', { name: `确认补充档案 v${profile.version}` })).toBeDisabled();
    expect(screen.getByRole('button', { name: '用原 JD 重新诊断并比较' })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it('requires confirmation of the new draft and reruns exactly the original JD version', async () => {
    const draft = { ...structuredClone(profile), version: profile.version + 1, confirmed: false };
    vi.spyOn(api, 'sendMessage').mockResolvedValue({ task_id: 'answer-task' });
    vi.spyOn(api, 'task').mockResolvedValue(task('answer-task', draft, false));
    vi.spyOn(api, 'profile').mockResolvedValue(draft);
    vi.spyOn(api, 'confirmProfile').mockResolvedValue({ ...draft, confirmed: true });
    vi.spyOn(api, 'diagnose').mockResolvedValue({
      task_id: 'next-task',
      diagnosis_id: 'next-report',
    });
    page();
    fireEvent.change(screen.getByLabelText('你的真实补充'), {
      target: { value: '我用 SQL 查询课程项目中的订单数据。' },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交补充并整理草稿' }));
    await screen.findByRole('button', { name: `确认补充档案 v${draft.version}` });
    expect(api.sendMessage).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({
        content: '我用 SQL 查询课程项目中的订单数据。',
        diagnosis_focus: focus,
        questions_only: false,
      }),
      expect.any(String),
    );
    expect(screen.getByRole('button', { name: '用原 JD 重新诊断并比较' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: `确认补充档案 v${draft.version}` }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '用原 JD 重新诊断并比较' })).toBeEnabled(),
    );
    await waitFor(() => expect(screen.getByLabelText('当前地址')).not.toHaveTextContent('task='));
    expect(screen.getByLabelText('当前地址')).toHaveTextContent('requirement=r2');
    fireEvent.click(screen.getByRole('button', { name: '用原 JD 重新诊断并比较' }));
    await waitFor(() =>
      expect(api.diagnose).toHaveBeenCalledWith(
        {
          profile: { id: profile.id, version: draft.version },
          jobs: [item.job],
          model_id: app.modelId,
        },
        expect.any(String),
      ),
    );
    await waitFor(() =>
      expect(screen.getByLabelText('当前地址')).toHaveTextContent(
        `/diagnoses/next-report?before=${diagnosis.id}&job=${job.id}`,
      ),
    );
  });

  it('does not apply a resumed task for another requirement even when the profile matches', async () => {
    vi.spyOn(api, 'task').mockResolvedValue(
      task('other-task', { ...profile, version: 99 }, false, { ...focus, requirement_id: 'r3' }),
    );
    page('other-task');
    expect(await screen.findByRole('alert')).toHaveTextContent('此任务不属于当前岗位要求');
    expect(api.profile).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: `确认补充档案 v${profile.version}` }),
    ).toBeInTheDocument();
  });

  it('preserves the answer when submitting fails and retries with the same key and body', async () => {
    const send = vi.spyOn(api, 'sendMessage').mockRejectedValue(new Error('offline'));
    page();
    fireEvent.change(screen.getByLabelText('你的真实补充'), {
      target: { value: '我没有使用过 SQL。' },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交补充并整理草稿' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('你的真实补充')).toHaveValue('我没有使用过 SQL。');
    fireEvent.click(screen.getByRole('button', { name: '提交补充并整理草稿' }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[0]).toEqual(send.mock.calls[1]);
  });

  it('keeps the current newer profile when reopening an old completed task URL', async () => {
    vi.spyOn(api, 'task').mockResolvedValue(task('old-task', profile, true));
    const newer = { ...profile, version: profile.version + 2 };
    page('old-task', newer);
    await screen.findByText(/已保留当前较新的/);
    expect(api.profile).not.toHaveBeenCalled();
    expect(
      screen.getByRole('heading', { name: `核对当前档案 · v${newer.version}` }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '生成岗位定向问题' })).toBeEnabled();
  });

  it('does not overwrite edits when retrying a failed result read', async () => {
    vi.spyOn(api, 'task').mockResolvedValue(task('read-task', profile, true));
    vi.spyOn(api, 'profile').mockRejectedValueOnce(new Error('result read failed'));
    page('read-task');
    await screen.findByText('result read failed');
    fireEvent.click(screen.getByText('查看并核对事实与证据'));
    fireEvent.change(screen.getByLabelText('经历概述'), { target: { value: '我的未保存编辑' } });
    fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
    await screen.findByText(/任务结果未覆盖它们/);
    expect(screen.getByLabelText('经历概述')).toHaveValue('我的未保存编辑');
    expect(api.profile).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '保存补充后的档案' })).toBeEnabled();
  });

  it('unlocks the editor when navigating away during a pending result read', async () => {
    vi.spyOn(api, 'task').mockResolvedValue(task('pending-read', profile, true));
    vi.spyOn(api, 'profile').mockImplementation(() => new Promise(() => {}));
    page('pending-read');
    await waitFor(() => expect(api.profile).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: '生成岗位定向问题' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '模拟返回无任务页面' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '生成岗位定向问题' })).toBeEnabled(),
    );
  });

  it('allows leaving an inaccessible task while keeping the target context', async () => {
    vi.spyOn(api, 'task').mockRejectedValue(new ApiError(404, 'NOT_FOUND', '任务不存在'));
    page('missing-task');
    fireEvent.click(await screen.findByRole('button', { name: '关闭无法访问的任务' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '生成岗位定向问题' })).toBeEnabled(),
    );
    await waitFor(() => expect(screen.getByLabelText('当前地址')).not.toHaveTextContent('task='));
    expect(screen.getByLabelText('当前地址')).toHaveTextContent(`diagnosis=${diagnosis.id}`);
  });
});
