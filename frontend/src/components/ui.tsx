import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useApp } from '../state';
import { useElapsedSeconds, useTask } from '../hooks';
import type { Capability, Task } from '../types';
import type { Issues } from '../validation';

export const labels: Record<string, string> = {
  queued: '等待处理',
  running: '正在处理',
  succeeded: '已完成',
  partial: '部分完成',
  failed: '处理失败',
  pending: '等待评分',
  scoring: '正在评分',
  reporting: '生成报告',
  score_only: '仅评分',
  met: '已满足',
  unmet: '明确不满足',
  unknown: '尚待确认',
  credential: '证书 / 考试',
  availability: '可到岗安排',
  skill: '技能',
  experience: '工作经历',
  education: '教育',
  project: '项目',
  other: '其他',
  must: '必须',
  preferred: '优先',
  explicit_gap: '明确差距',
  partial_gap: '部分差距',
  needs_evidence: '待补证据',
  now: '现在开始',
  next_2_weeks: '未来两周',
  next_2_months: '未来两个月',
};
export function Status({ value, assessment = false }: { value: string; assessment?: boolean }) {
  return (
    <span className={`badge status-${value}`}>
      <span aria-hidden="true">●</span>{' '}
      {assessment && value === 'partial' ? '部分满足' : labels[value] || value}
    </span>
  );
}
export function Heading({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {children && <p className="lead">{children}</p>}
      </div>
      {action}
    </div>
  );
}
export function Loading({ text = '正在读取资料…' }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {text}
    </div>
  );
}
export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  const hint: Record<number, string> = {
    401: '请重新开始会话。',
    404: '请检查链接，或返回输入页重新开始。',
    409: '本地编辑已保留。请读取最新版本核对后再操作。',
    413: '请更换不超过 10 MiB 的文件。',
    415: '请使用文字 PDF 或 DOCX，也可以改用对话输入。',
    422: '请根据提示检查输入字段。',
    429: `请等待 ${e?.retryAfter || 1} 秒后重试。`,
  };
  const outputReasons: Record<string, string> = {
    JSON_INVALID: '模型未返回可解析的 JSON。',
    SCHEMA_INVALID: '模型返回内容的字段结构不符合要求。',
    OUTPUT_TRUNCATED:
      'AI 输出超过单次长度限制，内容不完整。这不是账户余额不足；可重新生成，已有评分仍保留。',
    UNSUPPORTED_NUMBERS: '建议含有对应引用证据未支持的数字或日期，报告已被拒绝。',
    REFERENCE_INVALID: '事实、岗位要求或证据的编号及原文引用未通过校验。',
    PROFILE_DATE_INVALID:
      '档案日期不一致：请核对起止月份与资料截止月份；截止月份不能晚于当前月份。',
    FUTURE_END_DATE:
      '结束月份晚于资料截止月份。预计毕业日期可以保留，但教育经历须标为在读，且入学月份不能在截止月份之后；工作或项目不能把未来日期当作已完成经历。',
    REPORT_VALIDATION_FAILED: '报告内容与冻结评分或原文证据不一致。',
    REPORT_GROUNDING_REJECTED: '独立核对发现建议缺少支持、存在矛盾或仍不确定，未展示该内容。',
    REPORT_REVIEW_INCOMPLETE: '事实核对结果未覆盖全部内容，评分仍可查看。',
    REPORT_REVIEW_INVALID: '事实核对返回的引用或核对结果无效，评分仍可查看。',
  };
  const codeHints: Record<string, string> = {
    MODEL_OUTPUT_INVALID: '未通过核对的 AI 内容不会展示，已有评分仍可查看。无需反复提交相同请求。',
    MODEL_TIMEOUT: '模型响应超时，已有结果仍可查看。稍后可重试原资料。',
    TASK_TIMEOUT: '任务已超过处理时限，请查看已保留的结果后再重试。',
    PROVIDER_UNAVAILABLE: '模型供应商暂时不可用，请稍后重试。',
    MODEL_UNAVAILABLE: '所选模型配置不可用，请检查服务端配置或选择其他可用模型。',
    INTERNAL_ERROR: '服务处理失败，请稍后重试；无需因此修改已接受的输入字段。',
  };
  const outputTitles: Record<string, string> = {
    JSON_INVALID: 'AI 返回内容未能读取，已有结果已保留。',
    SCHEMA_INVALID: 'AI 返回字段不完整，已有结果已保留。',
    OUTPUT_TRUNCATED: 'AI 返回内容未完成，已有结果已保留。',
    UNSUPPORTED_NUMBERS: 'AI 建议中的数字缺少依据，评分已保留。',
    REFERENCE_INVALID: 'AI 建议的引用未通过核对，评分已保留。',
    REPORT_VALIDATION_FAILED: 'AI 建议未通过资料核对，评分与证据已保留。',
    REPORT_GROUNDING_REJECTED: 'AI 建议未通过事实核对，评分与证据已保留。',
    REPORT_REVIEW_INCOMPLETE: 'AI 事实核对未完成，评分与证据已保留。',
    REPORT_REVIEW_INVALID: 'AI 事实核对结果不可用，评分与证据已保留。',
  };
  const title =
    e?.code === 'MODEL_OUTPUT_INVALID'
      ? outputTitles[String(e.details.reason_code)] || 'AI 内容未通过核对，已有结果已保留。'
      : error instanceof Error
        ? error.message
        : '操作失败，请重试。';
  return (
    <div className="notice error" role="alert">
      <strong>{title}</strong>
      {e && (
        <>
          <p>
            {codeHints[e.code] || hint[e.status] || '请稍后重试。'} <code>{e.code}</code>
          </p>
          {Object.entries(e.details)
            .filter(([field]) => field !== 'report_trace_id')
            .map(([field, value]) => (
              <p key={field}>
                {field === 'reason_code'
                  ? outputReasons[String(value)] || '模型输出未通过校验。'
                  : `${field}：${typeof value === 'string' ? value : JSON.stringify(value)}`}
              </p>
            ))}
          {typeof e.details.report_trace_id === 'string' && (
            <small>报告排查编号：{e.details.report_trace_id}</small>
          )}
          {e.requestId && <small>请求编号：{e.requestId}</small>}
        </>
      )}
      {retry && (
        <button type="button" className="button secondary small" onClick={retry}>
          重新读取
        </button>
      )}
    </div>
  );
}
export function ValidationErrors({ errors }: { errors: Issues }) {
  const reveal = (field: string) => {
    const element = document.getElementById(field);
    const disclosure = element?.querySelector('details');
    if (disclosure) disclosure.open = true;
    let parent = element?.parentElement;
    while (parent) {
      if (parent instanceof HTMLDetailsElement) parent.open = true;
      parent = parent.parentElement;
    }
    return element;
  };
  useEffect(() => {
    Object.keys(errors).forEach(reveal);
  }, [errors]);
  if (!Object.keys(errors).length) return null;
  return (
    <div className="notice error" role="alert">
      <strong>请修正后继续</strong>
      <ul>
        {Object.entries(errors).map(([field, message]) => (
          <li key={field}>
            <a
              href={`#${field}`}
              onClick={() => {
                const element = reveal(field);
                const input = element?.matches('input, textarea, select')
                  ? element
                  : element?.querySelector<HTMLElement>('input, textarea, select');
                input?.focus();
              }}
            >
              {message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
export function Empty({
  title,
  children,
  to,
  action,
}: {
  title: string;
  children: ReactNode;
  to?: string;
  action?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden="true">
        ＋
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
      {to && (
        <Link className="button" to={to}>
          {action || '开始添加'}
        </Link>
      )}
    </div>
  );
}
export function ModelPicker({
  capability,
  disabled = false,
}: {
  capability: Capability;
  disabled?: boolean;
}) {
  const { models, modelId, setModelId } = useApp();
  const available = models.filter((m) => m.capabilities.includes(capability));
  return (
    <label className="model-picker">
      本次任务模型
      <select
        aria-label="本次任务模型"
        value={available.some((m) => m.id === modelId) ? modelId : ''}
        disabled={disabled}
        onChange={(e) => setModelId(e.target.value)}
      >
        <option value="" disabled>
          请选择支持本任务的模型
        </option>
        {available.map((m) => (
          <option key={m.id} value={m.id}>
            {m.display_name} · {m.provider}
          </option>
        ))}
      </select>
      <small>切换仅影响之后提交的任务。</small>
    </label>
  );
}
export function useCanModel(capability: Capability) {
  const { models, modelId } = useApp();
  return models.some((m) => m.id === modelId && m.capabilities.includes(capability));
}
type TaskState = { task?: Task; error?: unknown; retry: () => void };

export const terminalTask = (status?: string) =>
  status === 'succeeded' || status === 'partial' || status === 'failed';

export function TaskProgress({
  id,
  onComplete,
  onDismiss,
  state,
}: {
  id: string;
  onComplete: (task: Task) => void;
  onDismiss?: () => void;
  /** Reuse a task the page already polls instead of starting a second poller. */
  state?: TaskState;
}) {
  const polled = useTask(state ? null : id);
  const { task, error, retry } = state ?? polled;
  const waiting = !terminalTask(task?.status);
  const elapsed = useElapsedSeconds(task?.created_at, waiting, task?.updated_at);
  const completed = useRef('');
  useEffect(() => {
    if (task && ['succeeded', 'partial'].includes(task.status) && completed.current !== task.id) {
      completed.current = task.id;
      onComplete(task);
    }
  }, [task, onComplete]);
  return (
    <section className="panel task-progress">
      <div className="row">
        <h2>{error ? '进度更新已暂停' : waiting ? '正在整理你的资料' : '资料处理已结束'}</h2>
        <Status value={task?.status || 'queued'} />
      </div>
      <p>任务已提交。可以留在此页等待，刷新页面也能继续查看进度。</p>
      {task && (
        <p className="hint" aria-live="off">
          {waiting ? '提交后已等待' : '处理耗时'} {elapsed} 秒
        </p>
      )}
      <small>
        任务编号：{id} · 模型：{task?.model_id || '读取中'}
      </small>
      {waiting && !error && (
        <Loading
          text={
            task?.status === 'running'
              ? '正在整理事实与原文证据，等待处理结果返回…'
              : '任务已提交，等待后台开始处理…'
          }
        />
      )}
      {waiting && !error && elapsed >= 60 && (
        <p className="notice warning">
          等待时间较长，任务尚未结束。无需重复提交；刷新本页可继续查看。
        </p>
      )}
      {error ? (
        <div className="notice warning" role="alert">
          <p>暂时无法读取最新进度，后台任务可能仍在继续。重新连接不会重新提交资料。</p>
          <button className="button secondary" onClick={retry}>
            重新连接进度
          </button>
        </div>
      ) : null}
      <ErrorNotice error={error} />
      {task?.error && (
        <>
          <ErrorNotice
            error={new ApiError(422, task.error.code, task.error.message, task.error.details)}
          />
          {onDismiss && (
            <button className="button secondary" onClick={onDismiss}>
              返回输入并重试
            </button>
          )}
        </>
      )}
    </section>
  );
}
/** Non-fatal parsing notes persisted on task.result.warnings (for example DOCX pagination). */
export function TaskWarnings({
  warnings,
  onDismiss,
}: {
  warnings: string[];
  onDismiss?: () => void;
}) {
  if (!warnings.length) return null;
  return (
    <section className="notice task-warnings" role="status">
      <strong>资料解析提示</strong>
      <ul>
        {warnings.map((warning, index) => {
          // The contract stores a stable code prefix plus a module-owned message.
          const match = /^([A-Z][A-Z0-9_]*):\s*(.*)$/.exec(warning);
          return (
            <li key={`${index}-${warning}`}>
              <span>{match ? match[2] : warning}</span>
              {match && <code className="warning-code">{match[1]}</code>}
            </li>
          );
        })}
      </ul>
      {onDismiss && (
        <button type="button" className="text-button" onClick={onDismiss}>
          知道了
        </button>
      )}
    </section>
  );
}
export function ConfirmDialog({
  open,
  title,
  children,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (open) ref.current?.showModal();
    else ref.current?.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <h2 id="dialog-title">{title}</h2>
      <div>{children}</div>
      <div className="actions">
        <button className="button secondary" disabled={busy} onClick={onCancel}>
          取消
        </button>
        <button className="button danger" disabled={busy} onClick={onConfirm}>
          {busy ? '正在删除…' : '确认删除全部资料'}
        </button>
      </div>
    </dialog>
  );
}
export function CopyText({ text }: { text: string }) {
  const [state, setState] = useState('复制建议');
  return (
    <button
      className="button secondary small"
      onClick={() =>
        void navigator.clipboard
          .writeText(text)
          .then(() => setState('已复制'))
          .catch(() => setState('无法复制，请手动选取文字'))
      }
    >
      {state}
    </button>
  );
}
