import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { ProfileEditor } from '../src/components/ProfileEditor';
import { JobEditor } from '../src/components/JobEditor';
import { ValidationErrors } from '../src/components/ui';
import { api } from '../src/api';
import type { Job, ProfileContent } from '../src/types';
import { validateProfile } from '../src/validation';
import profileFixture from '../../docs/examples/profile.json';
import jobFixture from '../../docs/examples/job.json';

function ProfileHarness() {
  const [value, setValue] = useState(structuredClone(profileFixture.content) as ProfileContent);
  const [errors, setErrors] = useState<Record<string, string>>({});
  return (
    <>
      <ValidationErrors errors={errors} />
      <ProfileEditor value={value} onChange={setValue} disabled={false} />
      <button onClick={() => setErrors(validateProfile(value))}>检查草稿</button>
    </>
  );
}

describe('compact confirmation', () => {
  it('shows summaries and opens editing without changing confirmed data', () => {
    const change = vi.fn();
    const content = structuredClone(profileFixture.content) as ProfileContent;
    content.facts[0].polarity = 'negative';
    render(<ProfileEditor value={content} onChange={change} disabled={false} />);
    const row = screen.getByRole('article', { name: '事实 1' });
    expect(row.querySelector('details')).not.toHaveAttribute('open');
    expect(within(row).getByText(/明确否认/, { selector: 'span' })).toBeVisible();
    expect(within(row).getByLabelText('事实标签')).not.toBeVisible();
    fireEvent.click(row.querySelector('summary')!);
    expect(within(row).getByLabelText('事实标签')).toBeVisible();
    expect(change).not.toHaveBeenCalled();
  });

  it('keeps a new fact open while entering its first characters', () => {
    render(<ProfileHarness />);
    fireEvent.click(screen.getByRole('button', { name: '＋ 添加事实' }));
    const row = screen.getAllByRole('article').at(-1)!;
    const label = within(row).getByLabelText('事实标签');
    expect(label).toBeVisible();
    fireEvent.change(label, { target: { value: '新项目' } });
    expect(label).toBeVisible();
    expect(label).toHaveValue('新项目');
  });

  it('reveals hidden invalid fields and preserves edits across closing and reopening', async () => {
    render(<ProfileHarness />);
    const row = screen.getByRole('article', { name: '事实 1' });
    const summary = row.querySelector('summary')!;
    fireEvent.click(summary);
    fireEvent.change(within(row).getByLabelText('事实标签'), { target: { value: '' } });
    fireEvent.click(summary);
    fireEvent.click(screen.getByRole('button', { name: '检查草稿' }));
    await waitFor(() => expect(within(row).getByLabelText('事实标签')).toBeVisible());
    expect(within(row).getByLabelText('事实标签')).toHaveValue('');
    fireEvent.click(screen.getByRole('link', { name: '请填写事实标签。' }));
    expect(within(row).getByLabelText('事实标签')).toHaveFocus();
  });

  it('opens the evidence section when its hidden new quote is invalid', async () => {
    render(<ProfileHarness />);
    fireEvent.click(screen.getByText(/查看全部原文依据/));
    fireEvent.click(screen.getByRole('button', { name: '＋ 添加手动证据' }));
    fireEvent.click(screen.getByText(/查看全部原文依据/));
    fireEvent.click(screen.getByRole('button', { name: '检查草稿' }));
    const quote = screen.getByLabelText(`证据原文 ${profileFixture.content.evidence.length + 1}`);
    await waitFor(() => expect(quote).toBeVisible());
  });

  it('shows ignored requirements and prevents confirmation until edits are saved', () => {
    const confirm = vi.spyOn(api, 'confirmJob');
    const job = structuredClone(jobFixture) as Job;
    job.confirmed = false;
    job.content.requirements.at(-1)!.ignored = true;
    job.content.requirements.at(-1)!.ignore_reason = '测试用户排除该项';
    const onDirty = vi.fn();
    render(<JobEditor initial={job} onDirty={onDirty} onSaved={vi.fn()} />);
    const row = screen.getByRole('article', { name: '要求 1' });
    const button = screen.getByRole('button', { name: `确认 JD v${job.version}` });
    expect(button).toBeEnabled();
    fireEvent.click(row.querySelector('summary')!);
    fireEvent.change(within(row).getByLabelText('匹配目标'), { target: { value: 'SQL' } });
    fireEvent.click(row.querySelector('summary')!);
    expect(button).toBeDisabled();
    expect(onDirty).toHaveBeenLastCalledWith(true);
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getAllByText(/已忽略/).length).toBeGreaterThan(0);
  });

  it('opens the invalid requirement when validation points to the row itself', async () => {
    const job = structuredClone(jobFixture) as Job;
    job.confirmed = false;
    job.content.requirements.push({ ...job.content.requirements[0], id: 'duplicate' });
    render(<JobEditor initial={job} onDirty={vi.fn()} onSaved={vi.fn()} />);
    const last = screen.getAllByRole('article').at(-1)!;
    expect(last.querySelector('details')).not.toHaveAttribute('open');
    fireEvent.click(screen.getByRole('button', { name: `确认 JD v${job.version}` }));
    await waitFor(() => expect(last.querySelector('details')).toHaveAttribute('open'));
  });
});
