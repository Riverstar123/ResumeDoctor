import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { api } from '../src/api';
import { ProfileVersionComparison } from '../src/components/ProfileVersionComparison';
import { compareProfileVersions } from '../src/lib/profileComparison';
import { JobReport, ReportPage } from '../src/pages/ReportPage';
import type { Diagnosis, DiagnosisItem, Job, Profile } from '../src/types';
import profileFixture from '../../docs/examples/profile.json';
import jobFixture from '../../docs/examples/job.json';
import itemFixture from '../../docs/examples/diagnosis-item.json';

vi.mock('../src/state', () => ({
  useApp: () => ({
    workspace: { diagnosisIds: ['before-report', 'after-report'] },
    patch: vi.fn(),
    models: [
      {
        id: 'test-model',
        capabilities: ['diagnosis_report'],
        display_name: '合成模型',
        provider: 'fake',
      },
    ],
    modelId: 'test-model',
    setModelId: vi.fn(),
  }),
}));

// These are explicit synthetic saved results, not a frontend implementation of M4 scoring.
function pair() {
  const job = structuredClone(jobFixture) as Job;
  const beforeProfile = structuredClone(profileFixture) as Profile;
  const afterProfile = structuredClone(beforeProfile);
  afterProfile.version = 2;
  afterProfile.content.evidence.push({
    id: 'e4',
    source_type: 'message',
    source_id: 'follow-up-message',
    quote: '在课程项目中使用 SQL 完成数据查询。',
    locator: null,
  });
  const oldItem = structuredClone(itemFixture) as DiagnosisItem;
  const newItem = structuredClone(oldItem);
  newItem.id = 'new-item';
  newItem.score_result!.score = 83.3;
  newItem.score_result!.assessments[1] = {
    ...newItem.score_result!.assessments[1],
    status: 'met',
    coefficient: 1,
    evidence_ids: ['e4'],
    reason: '新确认材料明确提供 SQL 项目应用证据。',
  };
  const diagnosis = (id: string, profile: Profile, item: DiagnosisItem): Diagnosis => ({
    id,
    task_id: `task-${id}`,
    status: 'succeeded',
    profile: { id: profile.id, version: profile.version },
    model_id: 'test-model',
    items: [item],
    created_at: '2026-11-05T00:00:00Z',
  });
  return {
    current: diagnosis('after-report', afterProfile, newItem),
    currentItem: newItem,
    currentProfile: afterProfile,
    job,
    baseline: diagnosis('before-report', beforeProfile, oldItem),
    baselineProfile: beforeProfile,
  };
}

describe('saved profile version comparison', () => {
  it('aligns requirements by ID and orders versions independently of report creation time', () => {
    const input = pair();
    input.baseline.created_at = '2026-11-06T00:00:00Z';
    input.currentItem.score_result!.assessments.reverse();
    input.baseline.items.push({
      ...structuredClone(input.baseline.items[0]),
      id: 'extra',
      job: { id: 'other-job', version: 1 },
    });
    const result = compareProfileVersions(input);
    expect(result.comparable).toBe(true);
    if (!result.comparable) return;
    expect(result.before.profile.version).toBe(1);
    expect(result.after.profile.version).toBe(2);
    expect(result.scoreChange).toBe(16.6);
    const sql = result.rows.find((row) => row.requirement.id === 'r2')!;
    expect(sql.before.status).toBe('partial');
    expect(sql.after.status).toBe('met');
    expect(sql.addedReferences).toEqual(['e4']);
    expect(sql.removedReferences).toEqual(['e2']);
    expect(result.rows.filter((row) => row.changed)).toHaveLength(1);
  });

  it('compares score-only results and preserves an unknown to explicitly unmet transition', () => {
    const input = pair();
    input.currentItem.status = 'score_only';
    input.currentItem.report = null;
    input.currentItem.score_result!.unknown_weight_ratio = 0;
    input.currentProfile.content.as_of_month = '2026-10';
    input.currentProfile.content.evidence.push({
      id: 'e5',
      source_type: 'message',
      source_id: 'denial',
      quote: '我没有使用过 Docker。',
      locator: null,
    });
    input.currentItem.score_result!.assessments[2] = {
      ...input.currentItem.score_result!.assessments[2],
      status: 'unmet',
      evidence_ids: ['e5'],
      reason: '用户明确否认 Docker 使用经历。',
    };
    const result = compareProfileVersions(input);
    expect(result.comparable).toBe(true);
    if (!result.comparable) return;
    expect(result.rows[2].before.status).toBe('unknown');
    expect(result.rows[2].after.status).toBe('unmet');
    expect(result.unknownPercentagePointChange).toBe(-16.67);
    expect(result.cutoffChanged).toBe(true);
  });

  it('keeps each snapshot quote when an evidence ID is reused with changed content', () => {
    const input = pair();
    input.currentProfile.content.evidence[0].quote = '新版本对同一段 Python 经历的修正。';
    const result = compareProfileVersions(input);
    expect(result.comparable).toBe(true);
    if (!result.comparable) return;
    expect(result.rows[0].changedReferences).toEqual(['e1']);
    expect(result.rows[0].beforeEvidence[0].quote).toBe(
      input.baselineProfile.content.evidence[0].quote,
    );
    expect(result.rows[0].afterEvidence[0].quote).toBe('新版本对同一段 Python 经历的修正。');
  });

  it.each([
    [
      'different profile',
      (input: ReturnType<typeof pair>) => {
        input.baseline.profile.id = 'another-profile';
      },
      '不同档案',
    ],
    [
      'same profile version',
      (input: ReturnType<typeof pair>) => {
        input.baseline.profile.version = 2;
      },
      '同一档案版本',
    ],
    [
      'unconfirmed profile',
      (input: ReturnType<typeof pair>) => {
        input.currentProfile.confirmed = false;
      },
      '已确认',
    ],
    [
      'wrong profile snapshot',
      (input: ReturnType<typeof pair>) => {
        input.currentProfile.version = 3;
      },
      '快照与报告版本不一致',
    ],
    [
      'different JD version',
      (input: ReturnType<typeof pair>) => {
        input.baseline.items[0].job.version = 2;
      },
      '相同的 JD 版本',
    ],
    [
      'missing score',
      (input: ReturnType<typeof pair>) => {
        input.baseline.items[0].score_result = null;
      },
      '保存的规则评分',
    ],
    [
      'different rule',
      (input: ReturnType<typeof pair>) => {
        input.baseline.items[0].score_result!.rule_version = 'coverage-v2';
      },
      '规则或匹配器版本不同',
    ],
    [
      'different matcher',
      (input: ReturnType<typeof pair>) => {
        input.baseline.items[0].score_result!.matcher_version = 'matcher-v2';
      },
      '规则或匹配器版本不同',
    ],
    [
      'missing requirement',
      (input: ReturnType<typeof pair>) => {
        input.baseline.items[0].score_result!.assessments.pop();
      },
      '要求与冻结 JD 不一致',
    ],
    [
      'missing frozen evidence',
      (input: ReturnType<typeof pair>) => {
        input.baselineProfile.content.evidence = [];
      },
      '对应冻结档案中找到',
    ],
  ])(
    'rejects %s instead of attributing its difference to the profile',
    (_name, change, message) => {
      const input = pair();
      change(input);
      expect(compareProfileVersions(input)).toMatchObject({
        comparable: false,
        reason: expect.stringContaining(message),
      });
    },
  );
});

function comparison(input = pair(), baselineId = input.baseline.id) {
  return (
    <MemoryRouter>
      <ProfileVersionComparison
        current={input.current}
        item={input.currentItem}
        profile={input.currentProfile}
        job={input.job}
        diagnosisIds={[input.baseline.id]}
        baselineId={baselineId}
        onBaselineChange={vi.fn()}
      />
    </MemoryRouter>
  );
}

describe('profile comparison interface', () => {
  it('loads the exact historical profile, displays saved changes and links both reports', async () => {
    const input = pair();
    input.currentProfile.content.as_of_month = '2026-10';
    vi.spyOn(api, 'diagnosis').mockResolvedValue(input.baseline);
    const readProfile = vi.spyOn(api, 'profile').mockResolvedValue(input.baselineProfile);
    const { container } = render(comparison(input));
    expect(await screen.findByText('变化 +16.6 分')).toBeInTheDocument();
    expect(readProfile).toHaveBeenCalledWith(input.baselineProfile.id, 1, expect.any(AbortSignal));
    expect(screen.getByText(/两个版本的资料截止月份不同/)).toBeInTheDocument();
    expect(screen.getByText(/变化不等于能力提升/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /打开较早档案的完整报告/ })).toHaveAttribute(
      'href',
      `/diagnoses/before-report?before=after-report&job=${input.job.id}`,
    );
    expect(container.querySelectorAll('.profile-comparison-row')).toHaveLength(4);
    fireEvent.click(screen.getByRole('checkbox', { name: '只看有变化的要求' }));
    expect(container.querySelectorAll('.profile-comparison-row')).toHaveLength(1);
    expect(
      within(screen.getByRole('region', { name: 'r2 档案 v2 的证据' })).getByText(
        '在课程项目中使用 SQL 完成数据查询。',
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('region', { name: 'r2 档案 v1 的证据' })).queryByText(
        '在课程项目中使用 SQL 完成数据查询。',
      ),
    ).not.toBeInTheDocument();
  });

  it('does not display a previous selection when a delayed baseline request finishes after switching', async () => {
    const input = pair();
    let finishOld!: (value: Diagnosis) => void;
    const delayed = new Promise<Diagnosis>((resolve) => {
      finishOld = resolve;
    });
    const newer = {
      ...structuredClone(input.current),
      id: 'third-report',
      profile: { ...input.current.profile, version: 3 },
    };
    const newerProfile = { ...structuredClone(input.currentProfile), version: 3 };
    vi.spyOn(api, 'diagnosis').mockImplementation((id) =>
      id === input.baseline.id ? delayed : Promise.resolve(newer),
    );
    vi.spyOn(api, 'profile').mockImplementation((_id, version) =>
      Promise.resolve(version === 3 ? newerProfile : input.baselineProfile),
    );
    const { rerender } = render(comparison(input));
    rerender(comparison(input, newer.id));
    expect(await screen.findByRole('heading', { name: '较新档案 v3' })).toBeInTheDocument();
    await act(async () => {
      finishOld(input.baseline);
    });
    expect(screen.queryByRole('heading', { name: '较早档案 v1' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '较新档案 v3' })).toBeInTheDocument();
  });

  it('offers retry when the historical report is unavailable', async () => {
    const input = pair();
    vi.spyOn(api, 'diagnosis')
      .mockRejectedValueOnce(new Error('历史报告读取失败'))
      .mockResolvedValue(input.baseline);
    vi.spyOn(api, 'profile').mockResolvedValue(input.baselineProfile);
    render(comparison(input));
    expect(await screen.findByRole('alert')).toHaveTextContent('历史报告读取失败');
    fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByText('变化 +16.6 分')).toBeInTheDocument();
  });

  it('exposes focused follow-up only for non-met requirements with a real report context', () => {
    const input = pair();
    const { rerender } = render(
      <MemoryRouter>
        <JobReport
          item={input.baseline.items[0]}
          profile={input.baselineProfile}
          job={input.job}
          diagnosisId={input.baseline.id}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('link', { name: '补充要求 r1 的经历' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '补充要求 r2 的经历' })).toHaveAttribute(
      'href',
      `/profiles/${input.baselineProfile.id}/follow-up?diagnosis=before-report&item=${input.baseline.items[0].id}&requirement=r2`,
    );
    expect(screen.getByRole('link', { name: '补充要求 r3 的经历' })).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <JobReport item={input.baseline.items[0]} profile={input.baselineProfile} job={input.job} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('link', { name: /补充要求/ })).not.toBeInTheDocument();
  });

  it('preselects the requested JD while preserving the independent model comparison', async () => {
    const input = pair();
    const secondJob = {
      ...structuredClone(input.job),
      id: 'second-job',
      content: { ...input.job.content, title: '第二个目标岗位' },
    };
    const secondItem = {
      ...structuredClone(input.currentItem),
      id: 'second-item',
      job: { id: secondJob.id, version: 1 },
    };
    input.current.items.push(secondItem);
    input.baseline.items.push({
      ...structuredClone(input.baseline.items[0]),
      id: 'old-second-item',
      job: secondItem.job,
    });
    vi.spyOn(api, 'diagnosis').mockImplementation((id) =>
      Promise.resolve(id === input.current.id ? input.current : input.baseline),
    );
    vi.spyOn(api, 'profile').mockImplementation((_id, version) =>
      Promise.resolve(version === 1 ? input.baselineProfile : input.currentProfile),
    );
    vi.spyOn(api, 'job').mockImplementation((id) =>
      Promise.resolve(id === secondJob.id ? secondJob : input.job),
    );
    render(
      <MemoryRouter
        initialEntries={['/diagnoses/after-report?before=before-report&job=second-job']}
      >
        <Routes>
          <Route path="/diagnoses/:id" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('tab', { name: /第二个目标岗位/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(await screen.findByText('变化 +16.6 分')).toBeInTheDocument();
    expect(screen.getByLabelText('与另一份历史诊断比较')).toBeInTheDocument();
    expect(screen.getByLabelText('选择另一份诊断查看档案变化')).toHaveValue('before-report');
  });

  it('hides the old report while navigation is fetching a different diagnosis', async () => {
    const input = pair();
    input.currentItem.report!.summary = '当前报告独有摘要';
    let finish!: (value: Diagnosis) => void;
    const pending = new Promise<Diagnosis>((resolve) => {
      finish = resolve;
    });
    vi.spyOn(api, 'diagnosis').mockImplementation((id) =>
      id === input.current.id ? Promise.resolve(input.current) : pending,
    );
    vi.spyOn(api, 'profile').mockResolvedValue(input.currentProfile);
    vi.spyOn(api, 'job').mockResolvedValue(input.job);
    render(
      <MemoryRouter initialEntries={['/diagnoses/after-report']}>
        <Link to="/diagnoses/before-report">打开旧报告</Link>
        <Routes>
          <Route path="/diagnoses/:id" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('当前报告独有摘要')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '打开旧报告' }));
    await waitFor(() => expect(screen.queryByText('当前报告独有摘要')).not.toBeInTheDocument());
    await act(async () => {
      finish(input.baseline);
    });
    expect(await screen.findByText(input.baseline.items[0].report!.summary)).toBeInTheDocument();
  });

  it('accepts a canonicalized diagnosis ID without treating it as a different report', async () => {
    const input = pair();
    vi.spyOn(api, 'diagnosis').mockResolvedValue(input.current);
    vi.spyOn(api, 'profile').mockResolvedValue(input.currentProfile);
    vi.spyOn(api, 'job').mockResolvedValue(input.job);
    render(
      <MemoryRouter initialEntries={['/diagnoses/AFTER-REPORT']}>
        <Routes>
          <Route path="/diagnoses/:id" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(input.currentItem.report!.summary)).toBeInTheDocument();
  });
});
