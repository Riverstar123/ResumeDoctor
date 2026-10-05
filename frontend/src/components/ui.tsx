import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useApp } from '../state';
import { useTask } from '../hooks';
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
  unknown: '缺少证据',
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
  return (
    <div className="notice error" role="alert">
      <strong>{error instanceof Error ? error.message : '操作失败，请重试。'}</strong>
      {e && (
        <>
          <p>
            {hint[e.status] || '请稍后重试。'} <code>{e.code}</code>
          </p>
          {Object.entries(e.details).map(([field, value]) => (
            <p key={field}>
              {field}：{typeof value === 'string' ? value : JSON.stringify(value)}
            </p>
          ))}
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
  if (!Object.keys(errors).length) return null;
  return (
    <div className="notice error" role="alert">
      <strong>请修正后继续</strong>
      <ul>
        {Object.entries(errors).map(([field, message]) => (
          <li key={field}>
            <a href={`#${field}`}>{message}</a>
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
export function TaskProgress({
  id,
  onComplete,
  onDismiss,
}: {
  id: string;
  onComplete: (task: Task) => void;
  onDismiss?: () => void;
}) {
  const { task, error, retry } = useTask(id);
  const completed = useRef('');
  useEffect(() => {
    if (task && ['succeeded', 'partial'].includes(task.status) && completed.current !== task.id) {
      completed.current = task.id;
      onComplete(task);
    }
  }, [task, onComplete]);
  return (
    <section className="panel task-progress" aria-live="polite">
      <div className="row">
        <h2>正在整理你的资料</h2>
        <Status value={task?.status || 'queued'} />
      </div>
      <p>任务已提交。可以留在此页等待，刷新页面也能继续查看进度。</p>
      <small>
        任务编号：{id} · 模型：{task?.model_id || '读取中'}
      </small>
      {!task || !['failed', 'succeeded', 'partial'].includes(task.status) ? (
        <Loading text="提取事实与原文证据…" />
      ) : null}
      <ErrorNotice error={error} retry={retry} />
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
