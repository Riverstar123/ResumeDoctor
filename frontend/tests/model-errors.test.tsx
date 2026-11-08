import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import type { Task } from '../src/types';
import { ErrorNotice, TaskProgress } from '../src/components/ui';
import { ApiError } from '../src/api/client';
describe('output rejection guidance', () => {
  it('shows the safe report trace reference with a readable label', () => {
    const trace = '00000000-0000-4000-8000-000000000076';
    render(
      <ErrorNotice
        error={
          new ApiError(422, 'MODEL_OUTPUT_INVALID', '报告校验失败', {
            reason_code: 'REPORT_GROUNDING_REJECTED',
            report_trace_id: trace,
          })
        }
      />,
    );
    expect(screen.getByText(`报告排查编号：${trace}`)).toBeInTheDocument();
    expect(screen.queryByText(/report_trace_id：/)).not.toBeInTheDocument();
  });
  it.each([
    ['REPORT_GROUNDING_REJECTED', 'AI 建议未通过内容校对，评分与证据已保留。'],
    ['REPORT_REVIEW_INCOMPLETE', 'AI 内容校对未完成，评分与证据已保留。'],
    ['REPORT_REVIEW_INVALID', 'AI 内容校对结果不可用，评分与证据已保留。'],
  ])('shows a specific review outcome for %s', (reason, title) => {
    render(
      <ErrorNotice
        error={
          new ApiError(422, 'MODEL_OUTPUT_INVALID', '模型输出不符合要求，请重试', {
            reason_code: reason,
          })
        }
      />,
    );
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.queryByText('模型输出不符合要求，请重试')).not.toBeInTheDocument();
  });
  it('identifies evidence review failure without asking for another paid retry', () => {
    render(
      <ErrorNotice
        error={
          new ApiError(422, 'MODEL_OUTPUT_INVALID', '模型输出不符合要求，请重试', {
            reason_code: 'REPORT_VALIDATION_FAILED',
          })
        }
      />,
    );
    expect(screen.getByText('AI 建议未通过资料核对，评分与证据已保留。')).toBeInTheDocument();
    expect(screen.queryByText('模型输出不符合要求，请重试')).not.toBeInTheDocument();
    expect(screen.queryByText('模型返回内容的字段结构不符合要求。')).not.toBeInTheDocument();
  });
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
