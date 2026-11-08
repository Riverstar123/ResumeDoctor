import { Link } from 'react-router-dom';
import { useElapsedSeconds } from '../hooks';
import type { Diagnosis, Job } from '../types';

export function DiagnosisProgress({
  diagnosis,
  jobs,
  modelName,
  lastSyncedAt,
  disconnected,
  reconnect,
  viewItem,
}: {
  diagnosis: Diagnosis;
  jobs: Job[];
  modelName: string;
  lastSyncedAt: number;
  disconnected: boolean;
  reconnect: () => void;
  viewItem: (id: string) => void;
}) {
  const elapsed = useElapsedSeconds(diagnosis.created_at);
  const sinceSync = Math.max(0, Math.floor((Date.now() - lastSyncedAt) / 1000));
  const total = diagnosis.items.length;
  const scored = diagnosis.items.filter((item) => item.score_result !== null);
  const reports = diagnosis.items.filter((item) => item.status === 'succeeded');
  const finished = diagnosis.items.filter((item) =>
    ['succeeded', 'score_only', 'failed'].includes(item.status),
  );
  const generating = diagnosis.items.find((item) => item.status === 'reporting');
  const scoring = diagnosis.items.find((item) => item.status === 'scoring');
  const current = generating || scoring;
  const job = jobs.find((entry) => entry.id === current?.job.id);
  const currentName = current
    ? job?.content.title || `岗位 ${diagnosis.items.indexOf(current) + 1}`
    : '';

  return (
    <section className={`panel diagnosis-progress${disconnected ? ' disconnected' : ''}`}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">诊断进度</p>
          <h2>
            {disconnected
              ? '进度更新已暂停'
              : scored.length
                ? '报告正在生成，已有结果可以先看'
                : '任务已提交，正在准备诊断'}
          </h2>
        </div>
        <span className="tag">{modelName}</span>
      </div>
      <div role="status" aria-live="polite" aria-atomic="true">
        <p className="progress-current">
          {!disconnected && <span className="progress-pulse" aria-hidden="true" />}
          {disconnected
            ? '暂时无法读取最新进度，后台任务可能仍在继续。重新连接不会新建任务。'
            : current
              ? `${currentName}：${generating ? '自动评分已保存，正在整理基础报告' : '正在计算自动评分'}`
              : diagnosis.status === 'queued'
                ? '任务已提交，等待后台开始处理。'
                : '正在处理其余岗位，请稍候。'}
        </p>
        <p>
          已处理{' '}
          <strong>
            {finished.length} / {total}
          </strong>{' '}
          个岗位
          {finished.some((item) => item.status !== 'succeeded') && '（包含未生成报告的岗位）'}
        </p>
        <ol className="progress-steps">
          <li>✓ 档案与岗位要求已确认</li>
          <li>
            自动评分已完成：{scored.length} / {total}
          </li>
          <li>
            报告已生成：{reports.length} / {total}
          </li>
        </ol>
      </div>
      <progress aria-label="已处理岗位" max={total} value={finished.length} />
      <p className="hint" aria-live="off">
        提交后已等待 {elapsed} 秒 · 最近成功同步：{sinceSync} 秒前
      </p>
      {!disconnected && elapsed >= 60 && (
        <p className="notice warning">
          等待时间较长，最近读取的任务仍未结束。生成耗时会随内容和模型变化，已有评分与报告可以先查看。
        </p>
      )}
      <div className="actions">
        {disconnected && (
          <button className="button secondary" onClick={reconnect}>
            重新连接进度
          </button>
        )}
        {reports[0] && (
          <button className="button secondary" onClick={() => viewItem(reports[0].id)}>
            查看已完成报告
          </button>
        )}
        {scored[0] && (
          <button className="button secondary" onClick={() => viewItem(scored[0].id)}>
            先看自动评分
          </button>
        )}
        <Link className="text-link" to="/history">
          返回诊断记录
        </Link>
      </div>
      <p className="hint">
        刷新页面可继续查看；关闭页面不会取消后台任务。全部岗位处理结束后可统一导出 Markdown。
      </p>
    </section>
  );
}
