import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { EnhancementPanel } from '../src/components/EnhancementPanel';
import { JobReport } from '../src/pages/ReportPage';
import { api } from '../src/api';
import { mockModels } from '../src/api/mock';
import fixture from '../../docs/examples/diagnosis-item.json';
import job from '../../docs/examples/job.json';
import profile from '../../docs/examples/profile.json';
import type { DiagnosisItem, Job, Profile } from '../src/types';

vi.mock('../src/state', () => ({
  useApp: () => ({ models: mockModels.items, modelId: 'demo-model-a', setModelId: vi.fn() }),
}));
afterEach(() => vi.restoreAllMocks());
const base = (): DiagnosisItem => ({
  ...(structuredClone(fixture) as DiagnosisItem),
  model_metadata: null,
  report: {
    ...(structuredClone(fixture.report) as NonNullable<DiagnosisItem['report']>),
    suggestions: [],
    actions: [],
  },
  enhancement: null,
});
function panel(item: DiagnosisItem, onStarted = vi.fn()) {
  return render(
    <MemoryRouter>
      <EnhancementPanel
        diagnosisId="diagnosis"
        item={item}
        job={job as Job}
        submitting={false}
        onReconnect={vi.fn()}
        onStarted={onStarted}
      />
      <JobReport item={item} job={job as Job} profile={profile as Profile} />
    </MemoryRouter>,
  );
}

describe('optional report enhancement', () => {
  it('shows accepted advice provenance after a later model fails without relabeling the base', () => {
    const item = base();
    item.enhancement_history = [
      {
        task_id: 'accepted',
        model_id: 'demo-model-a',
        status: 'succeeded',
        policy_version: 'enhancement-v1',
        requirement_ids: ['r1'],
        error: null,
        model_metadata: { ...fixture.model_metadata, model_id: 'demo-model-a' },
      },
      {
        task_id: 'failed',
        model_id: 'demo-model-b',
        status: 'failed',
        policy_version: 'enhancement-v1',
        requirement_ids: ['r2'],
        error: { code: 'MODEL_OUTPUT_INVALID', message: 'rejected', details: {} },
        model_metadata: null,
      },
    ];
    panel(item);
    expect(screen.getByText('建议生成记录')).toBeInTheDocument();
    expect(screen.getByText(/demo-model-a · 目标要求：r1/)).toBeInTheDocument();
    expect(screen.queryByText('实际报告模型')).not.toBeInTheDocument();
    expect(document.querySelector('.model-metadata')?.textContent).not.toContain('demo-model-b');
  });

  it('does not request advice just because the base report is displayed', () => {
    const request = vi.spyOn(api, 'enhance');
    panel(base());
    expect(screen.getByText('评分已保存')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '岗位条件核对' })).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it('submits only the selected target and locks rapid repeat clicks', async () => {
    let resolve!: (value: { task_id: string }) => void;
    const request = vi.spyOn(api, 'enhance').mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const onStarted = vi.fn();
    const item = base();
    panel(item, onStarted);
    const checkbox = screen.getAllByRole('checkbox')[0];
    fireEvent.click(checkbox);
    const button = screen.getByRole('button', { name: '生成 AI 分析与改写' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0].slice(0, 3)).toEqual([
      'diagnosis',
      item.id,
      {
        model_id: 'demo-model-a',
        requirement_ids: [job.content.requirements[0].id],
      },
    ]);
    expect(screen.getByRole('button', { name: '正在处理建议…' })).toBeDisabled();
    resolve({ task_id: 'enhancement-task' });
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith('enhancement-task'));
  });
  it('keeps the base report visible after enhancement failure and explains server-side reuse', () => {
    const item = base();
    item.enhancement = {
      policy_version: 'enhancement-v1',
      task_id: 'enhancement-task',
      model_id: 'demo-model-a',
      status: 'failed',
      requirement_ids: job.content.requirements.filter((r) => !r.ignored).map((r) => r.id),
      error: { code: 'MODEL_OUTPUT_INVALID', message: 'rejected', details: {} },
      model_metadata: null,
    };
    panel(item);
    expect(screen.getByText(/本次未生成可用的新建议/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '岗位条件核对' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '生成 AI 分析与改写' })).toBeEnabled();
    expect(
      screen.getByText(/此前的分析记录已保留/),
    ).toBeInTheDocument();
    expect(screen.queryByText('模型输出不符合要求，请重试')).not.toBeInTheDocument();
  });
  it.each(['previous-task', 'updated-config-task'])(
    'lets the server decide config reuse when catalog cannot expose versions: %s',
    async (taskId) => {
      const item = base();
      item.enhancement_history = [
        {
          policy_version: 'older-policy',
          task_id: 'previous-task',
          model_id: 'demo-model-a',
          status: 'succeeded',
          requirement_ids: job.content.requirements.filter((r) => !r.ignored).map((r) => r.id),
          error: null,
          model_metadata: null,
        },
      ];
      const request = vi.spyOn(api, 'enhance').mockResolvedValue({ task_id: taskId });
      const onStarted = vi.fn();
      panel(item, onStarted);
      expect(request).not.toHaveBeenCalled();
      const button = screen.getByRole('button', { name: '生成 AI 分析与改写' });
      expect(button).toBeEnabled();
      fireEvent.click(button);
      await waitFor(() => expect(onStarted).toHaveBeenCalledWith(taskId));
      expect(request).toHaveBeenCalledTimes(1);
      expect(request).toHaveBeenCalledWith(
        'diagnosis',
        item.id,
        {
          model_id: 'demo-model-a',
          requirement_ids: [],
        },
        expect.any(String),
      );
    },
  );
});

it('replays the identical body after a lost response and reordered selection', async () => {
  const request = vi
    .spyOn(api, 'enhance')
    .mockRejectedValueOnce(new Error('响应丢失'))
    .mockResolvedValueOnce({ task_id: 'original-task' });
  const onStarted = vi.fn();
  panel(base(), onStarted);
  const boxes = screen.getAllByRole('checkbox');
  fireEvent.click(boxes[0]);
  fireEvent.click(boxes[1]);
  fireEvent.click(screen.getByRole('button', { name: '生成 AI 分析与改写' }));
  await screen.findByRole('alert');
  fireEvent.click(boxes[0]);
  fireEvent.click(boxes[0]);
  fireEvent.click(screen.getByRole('button', { name: '生成 AI 分析与改写' }));
  await waitFor(() => expect(onStarted).toHaveBeenCalledWith('original-task'));
  expect(request).toHaveBeenCalledTimes(2);
  expect(request.mock.calls[1]).toEqual(request.mock.calls[0]);
});
