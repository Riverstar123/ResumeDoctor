import { afterEach, describe, expect, it, vi } from 'vitest';
import profile from '../../docs/examples/profile.json';
import job from '../../docs/examples/job.json';
import type { Profile, Job } from '../src/types';
import {
  currentMonth,
  emptyProfile,
  validateFile,
  validateProfile,
  validateJob,
} from '../src/validation';

describe('Beijing business calendar', () => {
  afterEach(() => vi.useRealTimers());
  it.each([
    ['2026-10-31T15:59:59Z', '2026-10', '2026-11'],
    ['2026-10-31T16:00:00Z', '2026-11', '2026-12'],
    ['2026-12-31T16:00:00Z', '2027-01', '2027-02'],
    ['2026-02-28T16:00:00Z', '2026-03', '2026-04'],
  ])('uses the business month at %s regardless of browser timezone', (instant, month, future) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(instant));
    expect(currentMonth()).toBe(month);
    const content = emptyProfile();
    expect(content.as_of_month).toBe(month);
    expect(validateProfile(content)).toEqual({});
    expect(validateProfile({ ...content, as_of_month: future })).toHaveProperty('as_of_month');
  });
});

describe('input limits and evidence integrity', () => {
  it('allows expected graduation only for already-started in-progress education', () => {
    const content = structuredClone((profile as Profile).content);
    const fact = content.facts[2];
    fact.start_month = '2024-09';
    fact.end_month = '2027-06';
    fact.completed = false;
    expect(validateProfile(content)).toEqual({});
    fact.completed = true;
    expect(validateProfile(content)['facts.2.dates']).toContain('预计毕业');
    fact.completed = null;
    expect(validateProfile(content)).toHaveProperty('facts.2.dates');
    fact.completed = false;
    fact.start_month = '2027-01';
    expect(validateProfile(content)).toHaveProperty('facts.2.dates');
    fact.start_month = '2024-09';
    fact.kind = 'experience';
    fact.value = null;
    expect(validateProfile(content)).toHaveProperty('facts.2.dates');
  });
  it('accepts documented fixtures', () => {
    expect(validateProfile((profile as Profile).content)).toEqual({});
    expect(validateJob(job.raw_text, (job as Job).content)).toEqual({});
  });
  it('preserves an unknown education value while rejecting unsupported degrees', () => {
    const content = structuredClone((profile as Profile).content);
    const education = content.facts.find((fact) => fact.kind === 'education')!;
    const index = content.facts.indexOf(education);
    education.value = null;
    expect(validateProfile(content)).toEqual({});
    education.value = 'unsupported-degree';
    expect(validateProfile(content)).toHaveProperty(`facts.${index}.value`);
  });
  it('checks file extension, empty content and 10 MiB limit', () => {
    expect(validateFile(new File(['x'], 'resume.doc'))).toContain('仅支持');
    expect(validateFile(new File([], 'resume.pdf'))).toContain('为空');
    expect(validateFile(new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'resume.pdf'))).toContain(
      '10 MiB',
    );
    expect(validateFile(new File(['synthetic'], 'resume.docx'))).toBe('');
  });
  it('rejects dangling evidence and reversed months', () => {
    const content = structuredClone((profile as Profile).content);
    content.facts[0].evidence_ids = ['missing'];
    content.facts[0].start_month = '2026-09';
    content.facts[0].end_month = '2025-01';
    expect(validateProfile(content)).toHaveProperty('facts.0.evidence_ids');
    expect(validateProfile(content)).toHaveProperty('facts.0.dates');
  });
  it('rejects fabricated JD quotes, duplicate scoring requirements and all ignored', () => {
    const content = structuredClone((job as Job).content);
    content.requirements[0].quote = '不在原文中';
    content.requirements.push({ ...content.requirements[1], id: 'another' });
    expect(Object.values(validateJob(job.raw_text, content)).join(' ')).toContain('真实片段');
    expect(Object.values(validateJob(job.raw_text, content)).join(' ')).toContain('重复要求');
    content.requirements.forEach((r) => {
      r.ignored = true;
      r.ignore_reason = '个人属性';
    });
    expect(validateJob(job.raw_text, content).requirements).toContain('至少保留');
  });
});
