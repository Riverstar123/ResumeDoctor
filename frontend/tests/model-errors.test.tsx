import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import type { Task } from '../src/types';
import { ErrorNotice, TaskProgress } from '../src/components/ui';
import { ApiError } from '../src/api/client';
describe('output rejection guidance', () => {
  it('explains output length rather than an account balance problem', () => {
    render(
      <ErrorNotice
        error={
          new ApiError(422, 'MODEL_OUTPUT_INVALID', '输出不完整', {
            reason_code: 'OUTPUT_TRUNCATED',
          })
        }
      />,
    );
    expect(screen.getByText(/不是账户余额不足/)).toBeInTheDocument();
    expect(screen.queryByText(/预算上限/)).not.toBeInTheDocument();
  });
  it('explains future graduation and does not blame accepted input', () => {
    render(
      <ErrorNotice
        error={
          new ApiError(422, 'MODEL_OUTPUT_INVALID', '模型输出不符合要求', {
            reason_code: 'FUTURE_END_DATE',
          })
        }
      />,
    );
    expect(screen.getByText(/预计毕业日期可以保留/)).toBeInTheDocument();
    expect(screen.queryByText(/请根据提示检查输入字段/)).not.toBeInTheDocument();
  });
  it('does not blame input fields for a model rejection', () => {
    render(
      <ErrorNotice
        error={
          new ApiError(422, 'MODEL_OUTPUT_INVALID', '模型输出不符合要求', {
            reason_code: 'UNSUPPORTED_NUMBERS',
          })
        }
      />,
    );
    expect(screen.queryByText(/请根据提示检查输入字段/)).not.toBeInTheDocument();
    expect(screen.getByText(/已有评分仍可查看/)).toBeInTheDocument();
    expect(screen.getByText(/引用证据未支持的数字或日期/)).toBeInTheDocument();
  });
  it('keeps actual validation errors as input guidance', () => {
    render(<ErrorNotice error={new ApiError(422, 'VALIDATION_ERROR', '字段不合法')} />);
    expect(screen.getByText(/请根据提示检查输入字段/)).toBeInTheDocument();
  });
});

it('uses the persisted completion time after reload', () => {
  vi.useFakeTimers();
  try {
    vi.setSystemTime(new Date('2026-11-01T01:00:00Z'));
    render(
      <TaskProgress
        id="synthetic"
        onComplete={() => {}}
        state={{
          task: {
            id: 'synthetic',
            kind: 'profile_chat',
            model_id: 'demo-model-a',
            status: 'failed',
            created_at: '2026-11-01T00:00:00Z',
            updated_at: '2026-11-01T00:00:10Z',
            result: null,
            error: null,
          } as Task,
          error: undefined,
          retry: () => {},
        }}
      />,
    );
    expect(screen.getByText('处理耗时 10 秒')).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
