import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { DiagnosisProgress } from '../src/components/DiagnosisProgress';
import { JobReport, ReportPage } from '../src/pages/ReportPage';
import { AppProvider } from '../src/state';
import { api } from '../src/api';
import fixture from '../../docs/examples/diagnosis-item.json';
import profile from '../../docs/examples/profile.json';
import job from '../../docs/examples/job.json';
import type { Diagnosis, DiagnosisItem, Job, Profile, Task } from '../src/types';

const sample = fixture as DiagnosisItem;

const makeItem = (status: DiagnosisItem['status'], id = status): DiagnosisItem => ({
  ...(structuredClone(fixture) as DiagnosisItem),
  id,
  status,
  score_result: ['pending', 'scoring', 'failed'].includes(status) ? null : sample.score_result,
  report: status === 'succeeded' ? sample.report : null,
  model_metadata: status === 'succeeded' ? fixture.model_metadata : null,
});
const diagnosis = (items: DiagnosisItem[]): Diagnosis => ({
  id: 'diagnosis',
  task_id: 'existing-task',
  status: 'running',
  profile: { id: profile.id, version: 1 },
  model_id: 'demo-model-a',
  created_at: new Date().toISOString(),
  items,
});
const reconnect = vi.fn();
const viewItem = vi.fn();
const progress = (value: Diagnosis, disconnected = false) => (
  <MemoryRouter>
    <DiagnosisProgress
      diagnosis={value}
      jobs={[job as Job]}
      modelName="演示模型"
      lastSyncedAt={Date.now()}
      disconnected={disconnected}
      reconnect={reconnect}
      viewItem={viewItem}
    />
  </MemoryRouter>
);
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  sessionStorage.clear();
});

describe('truthful waiting feedback', () => {
  it('does not claim a queued job has a score or generated report', () => {
    const d = diagnosis([makeItem('pending')]);
    d.status = 'queued';
    render(progress(d));
    expect(screen.getByRole('heading', { name: '任务已提交，正在准备诊断' })).toBeInTheDocument();
    expect(screen.getByText('任务已提交，等待后台开始处理。')).toBeInTheDocument();
    expect(screen.getByText('自动评分已完成：0 / 1')).toBeInTheDocument();
    expect(screen.getByText('报告已生成：0 / 1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '先看自动评分' })).not.toBeInTheDocument();
  });
  it('counts failed and score-only jobs as processed, not as generated reports', () => {
    render(
      progress(
        diagnosis(
          ['succeeded', 'reporting', 'pending', 'score_only', 'failed'].map((s) =>
            makeItem(s as DiagnosisItem['status']),
          ),
        ),
      ),
    );
    expect(screen.getByText('3 / 5')).toBeInTheDocument();
    expect(screen.getByText('自动评分已完成：3 / 5')).toBeInTheDocument();
    expect(screen.getByText('报告已生成：1 / 5')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '3');
    expect(screen.getByText(/自动评分已保存，正在整理基础报告/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看已完成报告' }));
    expect(viewItem).toHaveBeenCalledWith('succeeded');
    expect(screen.getByRole('link', { name: '返回诊断记录' })).toHaveAttribute('href', '/history');
  });
  it('shows reconnection instead of an active-generation indicator when updates stop', () => {
    const { container } = render(progress(diagnosis([makeItem('reporting')]), true));
    expect(screen.getByRole('heading', { name: '进度更新已暂停' })).toBeInTheDocument();
    expect(container.querySelector('.progress-pulse')).toBeNull();
    expect(screen.getByText(/后台任务可能仍在继续/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新连接进度' }));
    expect(reconnect).toHaveBeenCalledTimes(1);
  });
  it('restores elapsed submission time and gives a long-wait message without a fake ETA', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-31T09:10:00Z'));
    const d = diagnosis([makeItem('reporting')]);
    d.created_at = '2026-10-31T09:08:30Z';
    render(progress(d));
    expect(screen.getByText(/提交后已等待 90 秒/)).toBeInTheDocument();
    expect(screen.getByText(/等待时间较长/)).toBeInTheDocument();
    expect(screen.queryByText(/预计剩余/)).not.toBeInTheDocument();
  });
  it('makes already-saved score and evidence readable before the report arrives', () => {
    render(
      <JobReport item={makeItem('reporting')} job={job as Job} profile={profile as Profile} />,
    );
    expect(screen.getByText(/AI 报告尚未完成/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '岗位条件核对' })).toBeInTheDocument();
    expect(screen.queryByText('让真实经历更有说服力')).not.toBeInTheDocument();
  });
  it('reconnects to the existing task without creating another paid diagnosis', async () => {
    const d = diagnosis([makeItem('reporting')]);
    vi.spyOn(api, 'diagnosis').mockResolvedValue(d);
    vi.spyOn(api, 'profile').mockResolvedValue(profile as Profile);
    vi.spyOn(api, 'job').mockResolvedValue(job as Job);
    const task = vi
      .spyOn(api, 'task')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ id: d.task_id, status: 'running' } as Task);
    const create = vi.spyOn(api, 'diagnose');
    render(
      <MemoryRouter initialEntries={['/diagnoses/diagnosis']}>
        <AppProvider>
          <Routes>
            <Route path="/diagnoses/:id" element={<ReportPage />} />
          </Routes>
        </AppProvider>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole('button', { name: '重新连接进度' }));
    await waitFor(() => expect(task).toHaveBeenCalledTimes(2));
    expect(task.mock.calls[0][0]).toBe('existing-task');
    expect(task.mock.calls[1][0]).toBe('existing-task');
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '用同一份材料再算一次' })).toBeDisabled();
  });
});

it('resumes an enhancement on an already completed diagnosis after reload', async () => {
  const item = makeItem('succeeded');
  item.report = { ...item.report!, suggestions: [], actions: [] };
  item.model_metadata = null;
  item.report_template_version = 'base-report-v1';
  item.enhancement = {
    policy_version: 'enhancement-v1',
    task_id: 'existing-enhancement',
    model_id: 'demo-model-a',
    status: 'running',
    requirement_ids: job.content.requirements.map((r) => r.id),
    error: null,
    model_metadata: null,
  };
  const initial = { ...diagnosis([item]), status: 'succeeded', model_id: null } as Diagnosis;
  const finished = structuredClone(initial);
  finished.items[0].enhancement!.status = 'failed';
  finished.items[0].enhancement!.error = { code: 'MODEL_TIMEOUT', message: 'synthetic timeout' };
  vi.spyOn(api, 'diagnosis').mockResolvedValueOnce(initial).mockResolvedValue(finished);
  vi.spyOn(api, 'profile').mockResolvedValue(profile as Profile);
  vi.spyOn(api, 'job').mockResolvedValue(job as Job);
  const task = vi
    .spyOn(api, 'task')
    .mockResolvedValue({ id: 'existing-enhancement', status: 'failed' } as Task);
  const create = vi.spyOn(api, 'enhance');
  render(
    <MemoryRouter initialEntries={['/diagnoses/diagnosis']}>
      <AppProvider>
        <Routes>
          <Route path="/diagnoses/:id" element={<ReportPage />} />
        </Routes>
      </AppProvider>
    </MemoryRouter>,
  );
  await screen.findByText(/本次未生成可用的新建议/);
  expect(task).toHaveBeenCalledWith('existing-enhancement', expect.any(AbortSignal));
  expect(create).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: /导出 Markdown/ })).toBeEnabled();
  expect(screen.getByRole('heading', { name: '岗位条件核对' })).toBeInTheDocument();
});

it('does not offer paid enhancement on a legacy report', async () => {
  const initial = { ...diagnosis([makeItem('succeeded')]), status: 'succeeded' } as Diagnosis;
  initial.items[0].report_template_version = null;
  vi.spyOn(api, 'diagnosis').mockResolvedValue(initial);
  vi.spyOn(api, 'profile').mockResolvedValue(profile as Profile);
  vi.spyOn(api, 'job').mockResolvedValue(job as Job);
  const create = vi.spyOn(api, 'enhance');
  render(
    <MemoryRouter initialEntries={['/diagnoses/diagnosis']}>
      <AppProvider>
        <Routes>
          <Route path="/diagnoses/:id" element={<ReportPage />} />
        </Routes>
      </AppProvider>
    </MemoryRouter>,
  );
  await screen.findByText('此为历史报告，可用当前材料重新生成基础报告后再获取建议。');
  expect(screen.queryByRole('button', { name: '生成 AI 分析与改写' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '用同一份材料再算一次' })).toBeEnabled();
  expect(create).not.toHaveBeenCalled();
});

it('shows confirmed coverage without a separate explanation of the original score', async () => {
  const item = makeItem('succeeded');
  const score = item.score_result!;
  const [met, partial] = score.assessments;
  const summary = '你的总分是100分。';
  item.report = { ...item.report!, summary };
  item.score_result = {
    ...score,
    score: 100,
    scorable_weight_ratio: 0.5,
    unknown_weight_ratio: 0.5,
    assessments: [
      met,
      {
        ...partial,
        status: 'unknown',
        coefficient: 0,
        unknown_reason: 'manual_review',
        counted_in_score: false,
      },
    ],
  };
  vi.spyOn(api, 'diagnosis').mockResolvedValue({ ...diagnosis([item]), status: 'succeeded' });
  vi.spyOn(api, 'profile').mockResolvedValue(profile as Profile);
  vi.spyOn(api, 'job').mockResolvedValue(job as Job);
  render(
    <MemoryRouter initialEntries={['/diagnoses/diagnosis']}>
      <AppProvider>
        <Routes>
          <Route path="/diagnoses/:id" element={<ReportPage />} />
        </Routes>
      </AppProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('tab', { name: /50\.0.*已证实覆盖分/ })).toBeVisible();
  expect(screen.queryByText(/原报告使用自动评分/)).not.toBeInTheDocument();
  expect(screen.queryByText('查看评分口径')).not.toBeInTheDocument();
  expect(screen.getByText(summary)).toBeVisible();
  expect(item.report.summary).toBe(summary);
});
