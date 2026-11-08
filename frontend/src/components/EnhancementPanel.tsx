import { useState } from 'react';
import { api } from '../api';
import { useAction } from '../hooks';
import { useApp } from '../state';
import type { DiagnosisItem, Job } from '../types';
import { ModelPicker, useCanModel } from './ui';

/** AI enhancement is optional and never gates access to the saved base report. */
export function EnhancementPanel({
  diagnosisId,
  item,
  job,
  submitting,
  pollError,
  onReconnect,
  onStarted,
}: {
  diagnosisId: string;
  item: DiagnosisItem;
  job?: Job;
  submitting: boolean;
  pollError?: unknown;
  onReconnect: () => void;
  onStarted: (taskId: string) => void;
}) {
  const app = useApp();
  const action = useAction();
  const canModel = useCanModel('diagnosis_report');
  const [selected, setSelected] = useState<string[]>([]);
  const enhancement = item.enhancement;
  const running = Boolean(enhancement && ['queued', 'running'].includes(enhancement.status));
  const requirements = job?.content.requirements.filter((r) => !r.ignored) || [];
  const targetIds = selected.length ? selected : requirements.map((r) => r.id);
  const hasHistory = [
    ...(item.enhancement_history || []),
    ...(enhancement ? [enhancement] : []),
  ].some(
    (entry) =>
      entry.model_id === app.modelId &&
      entry.requirement_ids.length === targetIds.length &&
      entry.requirement_ids.every((id) => targetIds.includes(id)) &&
      ['succeeded', 'partial', 'failed'].includes(entry.status),
  );
  const busy = submitting || running || action.busy;
  const requestIds = [...selected].sort();
  const start = () =>
    void action.run(
      async (key) => {
        const accepted = await api.enhance(
          diagnosisId,
          item.id,
          {
            model_id: app.modelId,
            requirement_ids: requestIds,
          },
          key,
        );
        onStarted(accepted.task_id);
      },
      JSON.stringify([diagnosisId, item.id, app.modelId, requestIds]),
    );
  return (
    <section className="panel" aria-label="个性化建议">
      <div className="section-heading">
        <div>
          <p className="eyebrow">按需增强</p>
          <h2>让建议聚焦你关心的要求</h2>
        </div>
        <span className="tag">基础报告已保存</span>
      </div>
      <p>
        基础报告可直接查看和导出。生成个性化建议会调用 AI；未通过核对的建议会略去，不影响已有报告。
      </p>
      {enhancement?.status === 'succeeded' && (
        <p className="notice success">本次建议处理已完成。下方仅展示通过核对的内容。</p>
      )}
      {enhancement?.status === 'partial' && (
        <p className="notice warning">
          未通过核对的候选已略去。基础报告仍可使用，下方仅展示可用内容。
        </p>
      )}
      {enhancement?.status === 'failed' && (
        <p className="notice warning" role="status">
          本次未生成可用的新建议，基础报告和已有内容仍可查看、导出。
          {typeof enhancement.error?.details?.report_trace_id === 'string' && (
            <small> 排查编号：{enhancement.error.details.report_trace_id}</small>
          )}
        </p>
      )}
      {hasHistory && (
        <p className="notice">
          该模型和范围已有处理记录；相同配置会复用已有结果。配置更新后可能生成新建议并调用 AI。
        </p>
      )}
      {(busy || Boolean(pollError)) && (
        <p className="notice" role="status">
          {pollError
            ? '建议进度暂时无法读取，后台任务可能仍在继续。'
            : '正在生成并核对建议，基础报告可以先查看。'}
        </p>
      )}
      {Boolean(pollError) && (
        <button className="button secondary small" onClick={onReconnect}>
          重新读取建议进度
        </button>
      )}
      {Boolean(action.error) && (
        <p className="notice warning" role="alert">
          {action.error instanceof Error ? action.error.message : '建议请求未完成。'}{' '}
          基础报告不受影响。
        </p>
      )}
      <details>
        <summary>选择需要建议的要求（默认当前岗位全部要求）</summary>
        {requirements.map((r) => (
          <label className="check" key={r.id}>
            <input
              type="checkbox"
              disabled={busy}
              checked={selected.includes(r.id)}
              onChange={(event) =>
                setSelected((ids) =>
                  event.target.checked ? [...ids, r.id] : ids.filter((id) => id !== r.id),
                )
              }
            />
            <span>{r.quote}</span>
          </label>
        ))}
      </details>
      <div className="rerun">
        <ModelPicker capability="diagnosis_report" disabled={busy} />
        <button
          className="button"
          disabled={busy || !canModel || !job || action.cooldown > 0}
          onClick={start}
        >
          {busy
            ? '正在处理建议…'
            : action.cooldown
              ? `${action.cooldown} 秒后可提交`
              : '请求当前岗位建议'}
        </button>
      </div>
    </section>
  );
}
