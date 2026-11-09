import type { Job, Schema } from '../types';

const excerpt = (text: string, limit: number) =>
  text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;

export function AnalysisOverview({
  report,
  job,
  scoreContext,
}: {
  report: Schema['ReportContent'];
  job?: Job;
  scoreContext?: string;
}) {
  const summary = report.summary.trim();
  const lead =
    summary.length > 180
      ? excerpt(summary.match(/^.+?[。！？].*?[。！？]/s)?.[0] || summary, 180)
      : summary;
  const actions = [...report.actions].sort((a, b) => a.priority.localeCompare(b.priority));
  return (
    <section className="panel analysis-overview" aria-labelledby="report-overview">
      <div className="section-heading">
        <h2 id="report-overview">AI 分析概览</h2>
      </div>
      <div className="analysis-lead">
        <h3>
          <span aria-hidden="true">01</span> 总结
        </h3>
        <p className="report-summary">{lead}</p>
        {(summary !== lead || scoreContext) && (
          <details>
            <summary>{summary !== lead ? '查看完整总结' : '查看评分口径'}</summary>
            {scoreContext && <p className="hint">{scoreContext}</p>}
            {summary !== lead && <p>{summary}</p>}
          </details>
        )}
      </div>
      <div className="analysis-grid">
        <section className="analysis-card">
          <h3>
            <span aria-hidden="true">02</span> 主要差距
          </h3>
          {report.gaps.length ? (
            <ul>
              {report.gaps.slice(0, 2).map((gap, index) => (
                <li key={`${gap.requirement_id}-${index}`}>
                  <strong>
                    {job?.content.requirements.find((r) => r.id === gap.requirement_id)?.quote ||
                      gap.requirement_id}
                  </strong>
                  <p>{excerpt(gap.description, 120)}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">本次分析未列出差距。</p>
          )}
        </section>
        <section className="analysis-card">
          <h3>
            <span aria-hidden="true">03</span> 修改方向
          </h3>
          {actions.length ? (
            <ol>
              {actions.slice(0, 2).map((action, index) => (
                <li key={`${action.requirement_id}-${index}`}>{excerpt(action.task, 140)}</li>
              ))}
            </ol>
          ) : (
            <p className="hint">本次分析未列出行动计划。</p>
          )}
        </section>
      </div>
      <a className="text-link" href="#report-insights">
        查看差距证据与完整行动计划 →
      </a>
    </section>
  );
}
