import { describe, expect, it } from 'vitest';
import profile from '../../docs/examples/profile.json';
import job from '../../docs/examples/job.json';
import type { Profile, Job } from '../src/types';
import { validateFile, validateProfile, validateJob } from '../src/validation';

describe('input limits and evidence integrity', () => {
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
