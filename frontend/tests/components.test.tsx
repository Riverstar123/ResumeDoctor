import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Status } from '../src/components/ui';
import { ProfileEditor } from '../src/components/ProfileEditor';
import { JobReport } from '../src/pages/ReportPage';
import { useAction } from '../src/hooks';
import fixture from '../../docs/examples/diagnosis-item.json';
import profile from '../../docs/examples/profile.json';
import job from '../../docs/examples/job.json';
import type { DiagnosisItem, Profile, Job } from '../src/types';

describe('frontend semantics', () => {
  it('distinguishes partial, unknown and explicitly unmet', () => {
    render(
      <>
        <Status value="partial" assessment />
        <Status value="unknown" assessment />
        <Status value="unmet" assessment />
      </>,
    );
    expect(screen.getByText('部分满足')).toBeInTheDocument();
    expect(screen.getByText('缺少证据')).toBeInTheDocument();
    expect(screen.getByText('明确不满足')).toBeInTheDocument();
  });
  it('keeps score and evidence available without an AI report', () => {
    const item = {
      ...fixture,
      status: 'score_only',
      report: null,
      error: { code: 'MODEL_TIMEOUT', message: '报告超时' },
    } as DiagnosisItem;
    render(<JobReport item={item} job={job as Job} profile={profile as Profile} />);
    expect(screen.getByText(/AI 报告未生成/)).toBeInTheDocument();
    expect(screen.getByText('逐条要求与证据')).toBeInTheDocument();
    expect(screen.queryByText('让真实经历更有说服力')).not.toBeInTheDocument();
  });
  it('renders untrusted model content as text', () => {
    const item = structuredClone(fixture) as DiagnosisItem;
    item.report!.summary = '<img src=x onerror=alert(1)>';
    const { container } = render(
      <JobReport item={item} job={job as Job} profile={profile as Profile} />,
    );
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });
  it('removing evidence removes dangling fact references so confirmation requires repair', () => {
    const change = vi.fn();
    render(
      <ProfileEditor value={(profile as Profile).content} onChange={change} disabled={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '删除证据 1' }));
    expect(change.mock.calls[0][0].facts[0].evidence_ids).toEqual([]);
  });
  it('reuses an idempotency key after a failed submission and rotates it after success', async () => {
    const request = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue('ok');
    function Harness() {
      const action = useAction();
      return (
        <button disabled={action.busy} onClick={() => void action.run(request, 'same-payload')}>
          提交
        </button>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled());
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    expect(request.mock.calls[0][0]).toBe(request.mock.calls[1][0]);
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled());
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
    expect(request.mock.calls[2][0]).not.toBe(request.mock.calls[1][0]);
  });
});
