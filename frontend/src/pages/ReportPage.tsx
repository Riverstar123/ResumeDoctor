import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api';
import { ApiError, isTerminal, pollTask } from '../api/client';
import { useAction, useLoad } from '../hooks';
import { useApp } from '../state';
import type { Diagnosis, DiagnosisItem, Evidence, Job, Profile } from '../types';
import {
  CopyText,
  Empty,
  ErrorNotice,
  Heading,
  Loading,
  ModelPicker,
  Status,
  labels,
  useCanModel,
} from '../components/ui';

const percent = (ratio: number) => `${(ratio * 100).toFixed(2)}%`;
const versionKey = (d: Diagnosis) =>
  JSON.stringify({
    profile: d.profile,
    jobs: d.items.map((i) => i.job).sort((a, b) => a.id.localeCompare(b.id)),
  });
export function ReportPage() {
  const { id = '' } = useParams();
  const load = useLoad((signal) => api.diagnosis(id, signal), id);
  const app = useApp();
  useEffect(() => {
    if (load.data && !app.workspace.diagnosisIds.includes(load.data.id))
      app.patch({ diagnosisIds: [load.data.id, ...app.workspace.diagnosisIds] });
  }, [load.data?.id]);
  return (
    <>
      {load.loading && <Loading text="正在读取诊断与冻结版本…" />}
      <ErrorNotice error={load.error} retry={load.reload} />
      {load.data && <ReportView key={id} initial={load.data} />}
    </>
  );
}
function ReportView({ initial }: { initial: Diagnosis }) {
  const [diagnosis, setDiagnosis] = useState(initial);
  const [active, setActive] = useState(initial.items[0].id);
  const [pollError, setPollError] = useState<unknown>();
  const [pollRevision, setPollRevision] = useState(0);
  const [compareId, setCompareId] = useState('');
  const app = useApp();
  const action = useAction();
  const download = useAction();
  const navigate = useNavigate();
  const canModel = useCanModel('diagnosis_report');
  const snapshots = useLoad(async (signal) => {
    const [profile, ...jobs] = await Promise.all([
      api.profile(initial.profile.id, initial.profile.version, signal),
      ...initial.items.map((item) => api.job(item.job.id, item.job.version, signal)),
    ]);
    return { profile: profile as Profile, jobs: jobs as Job[] };
  }, versionKey(initial));
  useEffect(() => {
    if (isTerminal(diagnosis.status) && !pollError) return;
    const controller = new AbortController();
    setPollError(undefined);
    const refresh = async () => {
      const next = await api.diagnosis(initial.id, controller.signal);
      if (!controller.signal.aborted) setDiagnosis(next);
    };
    void pollTask(api, initial.task_id, refresh, controller.signal).catch((error) => {
      if (!controller.signal.aborted) setPollError(error);
    });
    return () => controller.abort();
  }, [initial.id, pollRevision]);
  const terminal = isTerminal(diagnosis.status);
  const hasScore = diagnosis.items.some((i) => i.score_result !== null);
  const selected = diagnosis.items.find((i) => i.id === active) || diagnosis.items[0];
  const findJob = (item: DiagnosisItem) =>
    snapshots.data?.jobs.find((j) => j.id === item.job.id && j.version === item.job.version);
  const redo = () =>
    void action.run(
      async (key) => {
        const next = await api.diagnose(
          {
            profile: diagnosis.profile,
            jobs: diagnosis.items.map((i) => i.job),
            model_id: app.modelId,
          },
          key,
        );
        app.patch({
          diagnosisIds: [
            next.diagnosis_id,
            ...app.workspace.diagnosisIds.filter((id) => id !== next.diagnosis_id),
          ],
        });
        navigate(`/diagnoses/${next.diagnosis_id}`);
      },
      JSON.stringify([diagnosis.id, app.modelId]),
    );
  const exportReport = () =>
    void download.run(async () => {
      const text = await api.export(diagnosis.id);
      const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `ResumeDoctor-${diagnosis.id}.md`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  return (
    <>
      <Heading
        eyebrow="04 / 诊断结果"
        title={terminal ? '看清匹配，找到下一步。' : '正在逐个分析目标岗位'}
        action={
          <button
            className="button secondary"
            disabled={!terminal || !hasScore || download.busy || download.cooldown > 0}
            onClick={exportReport}
          >
            {download.busy ? '正在下载…' : '↓ 导出 Markdown'}
          </button>
        }
      >
        分数表示当前材料对岗位要求的覆盖程度，不是录用概率或能力排名。
      </Heading>
      <div className="report-meta">
        <Status value={diagnosis.status} />
        <span>档案 v{diagnosis.profile.version}</span>
        <span>
          任务模型：<strong>{diagnosis.model_id}</strong>
        </span>
        <span>{new Date(diagnosis.created_at).toLocaleString('zh-CN')}</span>
      </div>
      {!terminal && (
        <section className="notice" aria-live="polite">
          <Loading text="任务正在进行，约每 2 秒更新一次…" />
          <p>任务编号：{diagnosis.task_id}。刷新页面可继续查看；关闭页面不会取消后台任务。</p>
        </section>
      )}
      {diagnosis.status === 'partial' && (
        <p className="notice warning">
          部分岗位或 AI 报告未完成。已完成的评分与证据仍可查看和导出；可以使用同一快照重新诊断。
        </p>
      )}
      {diagnosis.status === 'failed' && (
        <p className="notice error" role="alert">
          本次诊断没有可用评分。请查看逐岗位错误，再重试诊断。
        </p>
      )}
      <ErrorNotice error={pollError} retry={() => setPollRevision((n) => n + 1)} />
      <ErrorNotice error={download.error} />
      <ErrorNotice error={snapshots.error} retry={snapshots.reload} />
      <div className="score-grid" role="tablist" aria-label="逐岗位报告">
        {diagnosis.items.map((item, i) => (
          <button
            role="tab"
            tabIndex={selected.id === item.id ? 0 : -1}
            aria-selected={selected.id === item.id}
            aria-controls="job-report"
            id={`tab-${item.id}`}
            className={`score-card ${selected.id === item.id ? 'selected' : ''}`}
            key={item.id}
            onClick={() => setActive(item.id)}
            onKeyDown={(event) => {
              const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
              if (!keys.includes(event.key)) return;
              event.preventDefault();
              const index =
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? diagnosis.items.length - 1
                    : (i + (event.key === 'ArrowRight' ? 1 : -1) + diagnosis.items.length) %
                      diagnosis.items.length;
              const next = diagnosis.items[index];
              setActive(next.id);
              document.getElementById(`tab-${next.id}`)?.focus();
            }}
          >
            <div className="row">
              <span className="eyebrow">岗位 {String(i + 1).padStart(2, '0')}</span>
              <Status value={item.status} />
            </div>
            <h2>{findJob(item)?.content.title || `岗位 ${i + 1}`}</h2>
            <p className="muted">
              {findJob(item)?.content.company_name || '公司未填写'} · JD v{item.job.version}
            </p>
            <div className="score-number">
              {item.score_result ? item.score_result.score.toFixed(1) : '—'}
              <small>/ 100</small>
            </div>
            <div className="score-track">
              <span style={{ width: `${item.score_result?.score || 0}%` }} />
            </div>
            <p className="unknown-caption">
              未知权重比例{' '}
              <strong>
                {item.score_result ? percent(item.score_result.unknown_weight_ratio) : '待计算'}
              </strong>
            </p>
          </button>
        ))}
      </div>
      <section id="job-report" role="tabpanel" aria-labelledby={`tab-${selected.id}`}>
        <JobReport item={selected} job={findJob(selected)} profile={snapshots.data?.profile} />
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">下一步</p>
            <h2>补充经历，或对比模型报告</h2>
          </div>
          <Link className="text-link" to={`/profiles/${diagnosis.profile.id}`}>
            补充档案 →
          </Link>
        </div>
        <p>
          重新诊断使用当前报告的冻结档案与 JD
          版本。切换报告模型不会重新提取材料，也不会修改历史报告。修改档案后，请到目标岗位页开始新诊断。
        </p>
        <div className="rerun">
          <ModelPicker capability="diagnosis_report" disabled={action.busy} />
          <button
            className="button"
            disabled={!terminal || action.busy || action.cooldown > 0 || !canModel}
            onClick={redo}
          >
            {action.busy
              ? '正在创建…'
              : action.cooldown
                ? `${action.cooldown} 秒后重试`
                : '用当前快照重新诊断'}
          </button>
        </div>
        <ErrorNotice error={action.error} />
        {app.workspace.diagnosisIds.filter((id) => id !== diagnosis.id).length > 0 && (
          <>
            <label className="field compare-picker">
              与另一份历史诊断比较
              <select value={compareId} onChange={(e) => setCompareId(e.target.value)}>
                <option value="">选择历史诊断</option>
                {app.workspace.diagnosisIds
                  .filter((id) => id !== diagnosis.id)
                  .map((id, i) => (
                    <option value={id} key={id}>
                      历史诊断 {i + 1} · {id.slice(0, 8)}
                    </option>
                  ))}
              </select>
            </label>
            {compareId && (
              <Comparison
                current={diagnosis}
                otherId={compareId}
                jobs={snapshots.data?.jobs || []}
              />
            )}
          </>
        )}
      </section>
    </>
  );
}
function EvidenceList({ ids, evidence }: { ids: string[]; evidence: Evidence[] }) {
  if (!ids.length) return <p className="hint">没有引用证据；不能据此断言不具备能力。</p>;
  return (
    <div className="evidence-list">
      {ids.map((id) => {
        const e = evidence.find((x) => x.id === id);
        return (
          <blockquote key={id}>
            <p>{e?.quote || '该证据尚未读取，请重新读取冻结档案。'}</p>
            <cite>
              {id} · {e?.source_type || '未知来源'} · {e?.source_id}{' '}
              {e?.locator ? `· ${e.locator}` : ''}
            </cite>
          </blockquote>
        );
      })}
    </div>
  );
}
export function JobReport({
  item,
  job,
  profile,
}: {
  item: DiagnosisItem;
  job?: Job;
  profile?: Profile;
}) {
  const score = item.score_result;
  const report = item.report;
  const evidence = profile?.content.evidence || [];
  const requirement = (id: string) => job?.content.requirements.find((r) => r.id === id);
  return (
    <>
      <ErrorNotice
        error={
          item.error
            ? new ApiError(422, item.error.code, item.error.message, item.error.details)
            : undefined
        }
      />
      {item.status === 'score_only' && (
        <p className="notice warning">
          AI 报告未生成。以下为已保留的确定性评分和规则明细，不包含 AI 修改建议。
        </p>
      )}
      {score && (
        <>
          <section className="panel">
            <div className="section-heading">
              <h2>材料覆盖概览</h2>
              <span className="tag">
                {score.rule_version} / {score.matcher_version}
              </span>
            </div>
            {report && <p className="report-summary">{report.summary}</p>}
            <div className="dimensions">
              {score.dimensions.map((d) => (
                <div className="dimension" key={d.category}>
                  <div className="row">
                    <span>{labels[d.category]}</span>
                    <strong>{d.score.toFixed(1)}</strong>
                  </div>
                  <div className="score-track">
                    <span style={{ width: `${d.score}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <p className="hint">
              总分由后端按要求权重计算，不能直接平均类别分数。未知项仍计入分母。
            </p>
          </section>
          <section className="panel">
            <div className="section-heading">
              <h2>逐条要求与证据</h2>
              <span className="count">{score.assessments.length}</span>
            </div>
            <div className="status-legend">
              {['met', 'partial', 'unmet', 'unknown'].map((s) => (
                <Status key={s} value={s} assessment />
              ))}
            </div>
            {score.assessments.map((a) => (
              <details className="assessment" key={a.requirement_id}>
                <summary>
                  <span className="assessment-title">
                    <small>
                      {a.requirement_id} · {labels[a.category]} · {labels[a.importance]}
                    </small>
                    <strong>{requirement(a.requirement_id)?.quote || a.requirement_id}</strong>
                  </span>
                  <Status value={a.status} assessment />
                </summary>
                <div className="assessment-body">
                  <p>{a.reason}</p>
                  <p className="hint">
                    要求权重 {a.weight} · 覆盖系数 {a.coefficient} · 证据 {a.evidence_ids.length} 条
                  </p>
                  <EvidenceList ids={a.evidence_ids} evidence={evidence} />
                </div>
              </details>
            ))}
            {job?.content.requirements
              .filter((r) => r.ignored)
              .map((r) => (
                <div className="ignored-requirement" key={r.id}>
                  <strong>已忽略 · {r.quote}</strong>
                  <p>{r.ignore_reason}</p>
                </div>
              ))}
          </section>
        </>
      )}
      {report && (
        <>
          <div className="report-columns">
            <section className="panel">
              <p className="eyebrow">GAPS / 差距与证据</p>
              <h2>先分清差在哪里</h2>
              {!report.gaps.length && <p className="empty-inline">本报告未列出差距。</p>}
              {report.gaps.map((gap, i) => (
                <article className="gap" key={`${gap.requirement_id}-${i}`}>
                  <span
                    className={`badge status-${gap.kind === 'needs_evidence' ? 'unknown' : gap.kind === 'explicit_gap' ? 'unmet' : 'partial'}`}
                  >
                    {labels[gap.kind]}
                  </span>
                  <h3>{gap.description}</h3>
                  <small>
                    关联要求：{gap.requirement_id} · {requirement(gap.requirement_id)?.quote}
                  </small>
                  <EvidenceList ids={gap.evidence_ids} evidence={evidence} />
                </article>
              ))}
            </section>
            <section className="panel">
              <p className="eyebrow">ACTIONS / 行动计划</p>
              <h2>把建议变成下一步</h2>
              {!report.actions.length && <p className="empty-inline">本报告未列出行动计划。</p>}
              {report.actions.map((a, i) => (
                <article className="action-item" key={`${a.requirement_id}-${i}`}>
                  <div className="row">
                    <span className="tag">{a.priority}</span>
                    <small>{labels[a.horizon]}</small>
                  </div>
                  <h3>{a.task}</h3>
                  <p>
                    <strong>完成标准</strong> · {a.done_when}
                  </p>
                  <small>关联要求：{a.requirement_id}</small>
                </article>
              ))}
            </section>
          </div>
          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">REWRITE / 修改建议</p>
                <h2>让真实经历更有说服力</h2>
              </div>
            </div>
            {!report.suggestions.length && <p className="empty-inline">本报告未列出改写建议。</p>}
            {report.suggestions.map((s, i) => (
              <article className="suggestion" key={`${s.requirement_id}-${i}`}>
                <div className="row">
                  <small>关联要求 {s.requirement_id}</small>
                  {s.requires_user_input && (
                    <span className="badge status-unknown">待填写真实信息</span>
                  )}
                </div>
                <div className="rewrite-grid">
                  <div>
                    <h3>原文</h3>
                    <p>{s.original || '没有可引用的原文'}</p>
                  </div>
                  <div className="revised">
                    <h3>建议表达</h3>
                    <p>{s.revised}</p>
                    <CopyText text={s.revised} />
                  </div>
                </div>
                <p className="hint">修改依据：{s.rationale}</p>
                {s.requires_user_input && (
                  <p className="notice warning">
                    方括号内容是待填写模板，仅在确实做过且可核实的情况下补充。
                  </p>
                )}
                <details>
                  <summary>查看建议引用证据</summary>
                  <EvidenceList ids={s.evidence_ids} evidence={evidence} />
                </details>
              </article>
            ))}
          </section>
        </>
      )}
      {item.model_metadata && (
        <div className="model-metadata">
          <strong>实际报告模型</strong>
          <span>
            {item.model_metadata.provider} / {item.model_metadata.model}
          </span>
          <span>
            {item.model_metadata.model_id} · {item.model_metadata.prompt_version} ·{' '}
            {item.model_metadata.gateway_config_version}
          </span>
          <small>生成于 {new Date(item.model_metadata.generated_at).toLocaleString('zh-CN')}</small>
        </div>
      )}
    </>
  );
}
function Comparison({
  current,
  otherId,
  jobs,
}: {
  current: Diagnosis;
  otherId: string;
  jobs: Job[];
}) {
  const other = useLoad((signal) => api.diagnosis(otherId, signal), otherId);
  return (
    <>
      <ErrorNotice error={other.error} retry={other.reload} />
      {other.loading && <Loading />}
      {other.data &&
        (versionKey(current) !== versionKey(other.data) ? (
          <p className="notice warning">
            两份诊断的档案或 JD 版本不同，不能用于验证“仅切换报告模型”的评分一致性。
            <Link to={`/diagnoses/${otherId}`}>打开历史报告</Link>
          </p>
        ) : (
          <div className="comparison">
            <p className="notice success">两份报告使用相同的冻结档案与 JD 版本。</p>
            <div className="table-scroll">
              <table>
                <caption>不同模型的独立岗位评分</caption>
                <thead>
                  <tr>
                    <th>岗位</th>
                    <th>{current.model_id}（当前）</th>
                    <th>{other.data.model_id}（历史）</th>
                  </tr>
                </thead>
                <tbody>
                  {current.items.map((item) => {
                    const previous = other.data!.items.find(
                      (i) => i.job.id === item.job.id && i.job.version === item.job.version,
                    );
                    return (
                      <tr key={item.id}>
                        <th>
                          {jobs.find((j) => j.id === item.job.id)?.content.title || item.job.id}
                        </th>
                        <td>
                          {item.score_result?.score ?? '暂无评分'} / 未知{' '}
                          {item.score_result
                            ? percent(item.score_result.unknown_weight_ratio)
                            : '—'}
                        </td>
                        <td>
                          {previous?.score_result?.score ?? '暂无评分'} / 未知{' '}
                          {previous?.score_result
                            ? percent(previous.score_result.unknown_weight_ratio)
                            : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Link className="text-link" to={`/diagnoses/${otherId}`}>
              阅读另一模型的完整报告 →
            </Link>
          </div>
        ))}
    </>
  );
}
export function HistoryPage() {
  const app = useApp();
  const load = useLoad(
    (signal) =>
      Promise.allSettled(app.workspace.diagnosisIds.map((id) => api.diagnosis(id, signal))),
    app.workspace.diagnosisIds.join(','),
  );
  return (
    <>
      <Heading eyebrow="04 / 历史记录" title="每一次诊断，都留有依据">
        此处记录当前标签页访问过的诊断。已保存的报告链接可在有效会话内重新读取。
      </Heading>
      {!app.workspace.diagnosisIds.length ? (
        <Empty title="还没有诊断记录" to="/jobs" action="前往目标岗位">
          确认档案和至少一个 JD 后，开始第一次诊断。
        </Empty>
      ) : (
        <>
          {load.loading && <Loading />}
          <ErrorNotice error={load.error} retry={load.reload} />
          <div className="history-list">
            {load.data?.map((entry, i) =>
              entry.status === 'fulfilled' ? (
                <Link
                  className="panel history-card"
                  to={`/diagnoses/${entry.value.id}`}
                  key={entry.value.id}
                >
                  <div>
                    <p className="eyebrow">
                      {new Date(entry.value.created_at).toLocaleString('zh-CN')}
                    </p>
                    <h2>
                      {entry.value.items.length} 个岗位 · 档案 v{entry.value.profile.version}
                    </h2>
                    <p>固定任务模型：{entry.value.model_id}</p>
                    <small>{entry.value.id}</small>
                  </div>
                  <Status value={entry.value.status} />
                  <span aria-hidden="true">→</span>
                </Link>
              ) : (
                <ErrorNotice
                  key={app.workspace.diagnosisIds[i]}
                  error={entry.reason}
                  retry={load.reload}
                />
              ),
            )}
          </div>
        </>
      )}
    </>
  );
}
