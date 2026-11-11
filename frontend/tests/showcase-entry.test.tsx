import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, isMock } from '../src/api';
import { IntakePage } from '../src/pages/IntakePage';
import { JobsPage } from '../src/pages/JobsPage';
import { showcaseCase } from '../src/showcaseCase';
import type { Profile } from '../src/types';
import profileFixture from '../../docs/examples/profile.json';

const app = vi.hoisted(() => ({
  workspace: {
    profileId: 'synthetic-profile',
    jobIds: [] as string[],
    selectedJobIds: [] as string[],
    diagnosisIds: [] as string[],
  },
  modelId: 'classroom-model',
  models: [
    {
      id: 'classroom-model',
      display_name: '课堂测试模型',
      provider: 'openai_compatible',
      capabilities: ['profile_extract', 'profile_chat', 'job_extract'],
    },
  ],
  setModelId: vi.fn(),
  patch: vi.fn(),
}));
vi.mock('../src/state', () => ({ useApp: () => app }));

beforeEach(() => {
  vi.spyOn(api, 'createProfile');
  vi.spyOn(api, 'sendMessage');
  vi.spyOn(api, 'createJob').mockImplementation(() => new Promise(() => {}));
  vi.spyOn(api, 'profile').mockResolvedValue(profileFixture as Profile);
  vi.spyOn(api, 'task').mockImplementation(() => new Promise(() => {}));
});

function intake(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <IntakePage />
    </MemoryRouter>,
  );
}

describe('classroom case in HTTP mode', () => {
  it('uses exactly the presentation resume and both original job descriptions', () => {
    expect(isMock).toBe(false);
    const scope = { window: {} as { resumeDoctorCase: typeof showcaseCase } };
    runInNewContext(readFileSync('public/showcase/case-data.js', 'utf8'), scope);
    expect(scope.window.resumeDoctorCase).toEqual(showcaseCase);
  });

  it('prefills an explicit example without submitting or replacing subsequent edits', () => {
    intake('/?example=1');
    expect(screen.getByRole('button', { name: '对话整理' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    const text = screen.getByRole('textbox', { name: '经历描述' });
    expect(text).toHaveValue(showcaseCase.resume);
    fireEvent.change(text, { target: { value: '自己修改的经历' } });
    expect(text).toHaveValue('自己修改的经历');
    fireEvent.change(text, { target: { value: '' } });
    expect(text).toHaveValue('');
    expect(api.createProfile).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '填入课堂合成简历' }));
    expect(text).toHaveValue(showcaseCase.resume);
  });

  it('keeps ordinary input blank and in upload mode', () => {
    intake('/');
    expect(screen.getByRole('button', { name: '上传简历' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: '对话整理' }));
    expect(screen.getByRole('textbox', { name: '经历描述' })).toHaveValue('');
  });

  it('prioritizes resuming a task over seeding an example', async () => {
    intake('/?example=1&task=existing-task');
    await waitFor(() => expect(api.task).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: '上传简历' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.queryByRole('textbox', { name: '经历描述' })).not.toBeInTheDocument();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it('fills both JDs only on request and locks example buttons during extraction', async () => {
    render(
      <MemoryRouter initialEntries={['/jobs']}>
        <JobsPage />
      </MemoryRouter>,
    );
    const input = screen.getByRole('textbox', { name: '职位描述（JD）' });
    const first = screen.getByRole('button', { name: '填入岗位 A：经营数据分析' });
    const second = screen.getByRole('button', { name: '填入岗位 B：财务分析' });
    expect(input).toHaveValue('');
    fireEvent.click(first);
    expect(input).toHaveValue(showcaseCase.jobs[0].text);
    fireEvent.click(second);
    expect(input).toHaveValue(showcaseCase.jobs[1].text);
    expect(api.createJob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /提取岗位要求/ }));
    await waitFor(() =>
      expect(api.createJob).toHaveBeenCalledExactlyOnceWith(
        { raw_text: showcaseCase.jobs[1].text, company_context: '', model_id: 'classroom-model' },
        expect.any(String),
      ),
    );
    expect(first).toBeDisabled();
    expect(second).toBeDisabled();
  });
});
