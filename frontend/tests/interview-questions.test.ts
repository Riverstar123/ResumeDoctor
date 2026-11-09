// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { buildInterviewQuestions, drawQuestions } from '../src/lib/interviewQuestions';
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
    {
      id: 'f4',
      kind: 'availability',
      label: '实习安排',
      value: null,
      polarity: 'positive',
      application: 'claimed',
      start_month: null,
      end_month: null,
      completed: null,
      evidence_ids: ['e1'],
      attributes: [
        { name: 'availability_days', value: '4', quote: '每周4天' },
        { name: 'availability_months', value: '3', quote: '3个月' },
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
    {
      id: 'r2',
      quote: '熟悉 Docker 者优先',
      category: 'skill',
      importance: 'preferred',
      operator: 'has_skill',
      target: 'Docker',
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
  {
    requirement_id: 'r2',
    category: 'skill',
    importance: 'preferred',
    status: 'unknown',
    weight: 1,
    coefficient: 0,
    evidence_ids: [],
    reason: '未提供 Docker 的对应证据。',
    unknown_reason: 'missing_evidence',
    counted_in_score: true,
  },
] as unknown as RequirementAssessment[];

describe('interview questions', () => {
  it('uses real resume facts in Chinese questions', () => {
    const { zh } = buildInterviewQuestions(profile, job, assessments);
    const text = zh.map((item) => item.text).join('\n');
    expect(text).toContain('行业研究');
    expect(text).toContain('中信证券');
    expect(text).toContain('2025 年 7 月');
    expect(text).toContain('华东师范大学');
    expect(text).toContain('Python');
    expect(text).toContain('每周 4 天');
    // Missing-evidence items are not turned into interview questions.
    expect(text).not.toContain('Docker');
  });

  it('builds English questions for the same facts', () => {
    const { en } = buildInterviewQuestions(profile, job, assessments);
    const text = en.map((item) => item.text).join('\n');
    expect(text).toContain('internship');
    expect(text).toContain('Python');
    expect(text).toContain('introduce yourself');
  });

  it('draws three questions without repeating across rounds', () => {
    const { zh } = buildInterviewQuestions(profile, job, assessments);
    const first = drawQuestions(zh, new Set(), 3);
    expect(first).toHaveLength(3);
    const used = new Set(first.map((item) => item.id));
    const second = drawQuestions(zh, used, 3);
    expect(second).toHaveLength(3);
    second.forEach((item) => expect(used.has(item.id)).toBe(false));
  });
});
