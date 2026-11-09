import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { MockInterview } from '../src/components/MockInterview';
import type { JobContent, ProfileContent, RequirementAssessment } from '../src/types';

const profile = {
  overview: '合成档案',
  as_of_month: '2026-11',
  facts: [
    {
      id: 'f1',
      kind: 'experience',
      label: '行业研究',
      value: null,
      polarity: 'positive',
      application: 'claimed',
      start_month: '2025-07',
      end_month: '2025-09',
      completed: null,
      evidence_ids: ['e1'],
      attributes: [
        { name: 'experience_domain', value: '行业研究', quote: '行业研究' },
        { name: 'experience_type', value: 'internship', quote: '实习' },
      ],
    },
    {
      id: 'f2',
      kind: 'project',
      label: 'Python',
      value: null,
      polarity: 'positive',
      application: 'applied',
      start_month: null,
      end_month: null,
      completed: null,
      evidence_ids: ['e1'],
      attributes: [],
    },
    {
      id: 'f3',
      kind: 'education',
      label: '金融',
      value: 'master',
      polarity: 'positive',
      application: 'claimed',
      start_month: null,
      end_month: null,
      completed: false,
      evidence_ids: ['e1'],
      attributes: [
        { name: 'institution', value: '华东师范大学', quote: '华东师范大学' },
        { name: 'major', value: '金融', quote: '金融' },
      ],
    },
  ],
  evidence: [
    {
      id: 'e1',
      source_type: 'manual',
      source_id: 'synthetic',
      quote: '2025年7月到9月在中信证券研究部做行业研究实习',
      locator: null,
    },
  ],
} as unknown as ProfileContent;

const job = {
  title: '行业研究实习生',
  company_name: null,
  company_context: '',
  requirements: [
    {
      id: 'r1',
      quote: '必须有 Python 项目应用经验',
      category: 'skill',
      importance: 'must',
      operator: 'has_skill',
      target: 'Python',
      subject: null,
      ignored: false,
      ignore_reason: null,
    },
  ],
} as unknown as JobContent;

const assessments = [
  {
    requirement_id: 'r1',
    category: 'skill',
    importance: 'must',
    status: 'met',
    weight: 2,
    coefficient: 1,
    evidence_ids: ['e1'],
    reason: '有应用证据',
    unknown_reason: null,
    counted_in_score: true,
  },
] as unknown as RequirementAssessment[];

describe('MockInterview', () => {
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
    };
  });

  it('opens one question at a time and finishes after three', () => {
    render(<MockInterview profile={profile} job={job} assessments={assessments} />);
    expect(screen.getByRole('button', { name: '中文面' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'English' })).toBeVisible();
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '中文面' }));
    expect(screen.getByRole('dialog')).toBeVisible();
    expect(screen.getByText('第 1 / 3 题')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    expect(screen.getByText('第 2 / 3 题')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    expect(screen.getByText('第 3 / 3 题')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '完成本轮' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: '再来一轮' })).toBeVisible();
  });

  it('keeps the current question when cancelled and restores focus', () => {
    render(<MockInterview profile={profile} />);
    fireEvent.click(screen.getByRole('button', { name: 'English' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog.querySelector('h2')).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    const resume = screen.getByRole('button', { name: '继续本轮' });
    expect(resume).toHaveFocus();
    fireEvent.click(resume);
    expect(screen.getByText('第 2 / 3 题')).toBeVisible();
  });

  it('draws the final two questions before allowing a restart', () => {
    render(<MockInterview profile={{ ...profile, facts: [profile.facts[1], profile.facts[2]] }} />);
    fireEvent.click(screen.getByRole('button', { name: 'English' }));
    for (let round = 0; round < 3; round++) {
      fireEvent.click(screen.getByRole('button', { name: '下一题' }));
      fireEvent.click(screen.getByRole('button', { name: '下一题' }));
      fireEvent.click(screen.getByRole('button', { name: '完成本轮' }));
      expect(screen.queryByText(/题库已抽完/)).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: '再来一轮' }));
    }
    expect(screen.getByText('第 1 / 2 题')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    fireEvent.click(screen.getByRole('button', { name: '完成本轮' }));
    expect(screen.getByText(/题库已抽完/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '重新开始' }));
    expect(screen.getByText('第 1 / 3 题')).toBeVisible();
  });
});
