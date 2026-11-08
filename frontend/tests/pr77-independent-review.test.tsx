import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ProfilePage } from '../src/pages/ProfilePage';
import { JobEditor } from '../src/components/JobEditor';
import { JobReport } from '../src/pages/ReportPage';
import { api } from '../src/api';
import { mockModels } from '../src/api/mock';
import profile from '../../docs/examples/profile.json';
import job from '../../docs/examples/job.json';
import item from '../../docs/examples/diagnosis-item.json';
import type { Profile, Job, DiagnosisItem } from '../src/types';
vi.mock('../src/state', () => ({
  useApp: () => ({
    models: mockModels.items,
    modelId: 'demo-model-a',
    setModelId: vi.fn(),
    patch: vi.fn(),
    workspace: { profileWarningTasks: {} },
    rememberProfileWarningTask: vi.fn(),
    dismissProfileWarnings: vi.fn(),
  }),
}));
beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
});
it('restores assistant questions and sends a further answer with the current version', async () => {
  vi.spyOn(api, 'profile').mockResolvedValue(structuredClone(profile) as Profile);
  vi.spyOn(api, 'messages').mockResolvedValue({
    items: [{ id: 'question', role: 'assistant', content: '请补充这段实习的起止月份' }],
  } as never);
  const send = vi.spyOn(api, 'sendMessage').mockReturnValue(new Promise(() => {}));
  render(
    <MemoryRouter initialEntries={['/profiles/' + profile.id]}>
      <Routes>
        <Route path="/profiles/:id" element={<ProfilePage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText('请补充这段实习的起止月份')).toBeVisible();
  fireEvent.change(screen.getByLabelText('补充经历'), { target: { value: '2025年6月到8月' } });
  fireEvent.click(screen.getByRole('button', { name: '发送补充' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      profile.id,
      { base_version: profile.version, content: '2025年6月到8月', model_id: 'demo-model-a' },
      expect.any(String),
    ),
  );
  expect(screen.getByRole('button', { name: '正在提交…' })).toBeDisabled();
});
it('updates JD summary immediately on add and delete, without saving', () => {
  const initial = structuredClone(job) as Job;
  initial.content.requirements = initial.content.requirements.slice(0, 1);
  initial.content.requirements[0].ignored = false;
  render(<JobEditor initial={initial} onDirty={vi.fn()} onSaved={vi.fn()} />);
  expect(screen.getByText('岗位要求已整理')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '＋ 添加要求' }));
  expect(screen.getByText('有 1 条要求需要核对')).toBeVisible();
  expect(screen.getByText(/识别出 2 条要求/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '删除要求 2' }));
  expect(screen.getByText('岗位要求已整理')).toBeVisible();
  expect(screen.getByText(/识别出 1 条要求/)).toBeVisible();
});
it.each(['other', 'skill'] as const)(
  'offers scored missing-evidence follow-up for %s',
  (category) => {
    const value = structuredClone(item) as DiagnosisItem;
    value.score_result!.assessments = [
      {
        ...value.score_result!.assessments[0],
        requirement_id: 'r1',
        category,
        status: 'unknown',
        unknown_reason: 'missing_evidence',
        counted_in_score: true,
      },
    ];
    render(
      <MemoryRouter>
        <JobReport
          item={value}
          profile={profile as Profile}
          job={job as Job}
          diagnosisId="diagnosis"
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: '补充要求 r1 的经历' })).toHaveAttribute(
      'href',
      expect.stringContaining('requirement=r1'),
    );
    expect(screen.getByText('还有 1 条影响分数，可在下方逐条补充。')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '定位第一条' }));
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce();
  },
);
it('does not offer manual unscored items as score improvements', () => {
  const value = structuredClone(item) as DiagnosisItem;
  value.score_result!.assessments = [
    {
      ...value.score_result!.assessments[0],
      requirement_id: 'r1',
      category: 'other',
      status: 'unknown',
      unknown_reason: 'manual_review',
      counted_in_score: false,
    },
  ];
  render(
    <MemoryRouter>
      <JobReport
        item={value}
        profile={profile as Profile}
        job={job as Job}
        diagnosisId="diagnosis"
      />
    </MemoryRouter>,
  );
  expect(screen.queryByRole('link', { name: '补充要求 r1 的经历' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '定位第一条' })).not.toBeInTheDocument();
});
