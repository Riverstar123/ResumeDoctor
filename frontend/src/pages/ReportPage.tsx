import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { ApiError, isTerminal, pollTask } from '../api/client';
import { useAction, useLoad } from '../hooks';
import { useApp } from '../state';
import type { Diagnosis, DiagnosisItem, Evidence, Job, Profile, Task } from '../types';
import { DiagnosisProgress } from '../components/DiagnosisProgress';
import { ReportSuggestions } from '../components/ReportSuggestions';
import { EnhancementPanel } from '../components/EnhancementPanel';
import { ProfileVersionComparison } from '../components/ProfileVersionComparison';
import { Empty, ErrorNotice, Heading, Loading, Status, labels } from '../components/ui';

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
      {load.loading && <Loading text="正在读取诊断与本次使用的版本…" />}
      <ErrorNotice error={load.error} retry={load.reload} />
      {load.data?.id.toLowerCase() === id.toLowerCase() && (
        <ReportView key={id} initial={load.data} />
      )}
    </>
  );
}
function ReportView({ initial }: { initial: Diagnosis }) {
  const [params, setParams] = useSearchParams();
  const requestedJob = params.get('job');
  const [diagnosis, setDiagnosis] = useState(initial);
  const [active, setActive] = useState(
    () => initial.items.find((item) => item.job.id === requestedJob)?.id || initial.items[0].id,
  );
  const [pollError, setPollError] = useState<unknown>();
  const [pollRevision, setPollRevision] = useState(0);
  const [lastSyncedAt, setLastSyncedAt] = useState(Date.now);
  const [compareId, setCompareId] = useState('');
  const [submittedEnhancement, setSubmittedEnhancement] = useState('');
  const [enhancementPollError, setEnhancementPollError] = useState<unknown>();
  const [enhancementRevision, setEnhancementRevision] = useState(0);
  const app = useApp();
  const action = useAction();
  const download = useAction();
  const navigate = useNavigate();
  useEffect(() => {
    const requested = diagnosis.items.find((item) => item.job.id === requestedJob);
    if (requested) setActive(requested.id);
  }, [requestedJob, diagnosis.items]);
  const selectItem = (id: string) => {
    const item = diagnosis.items.find((candidate) => candidate.id === id);
    if (!item) return;
    setActive(id);
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('job', item.job.id);
        return next;
      },
      { replace: true },
    );
  };
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
      if (!controller.signal.aborted) {
        setDiagnosis(next);
        setLastSyncedAt(Date.now());
      }
    };
    void pollTask(api, initial.task_id, refresh, controller.signal).catch((error) => {
      if (!controller.signal.aborted) setPollError(error);
    });
    return () => controller.abort();
  }, [initial.id, pollRevision]);
  const enhancementTaskIds = [
    ...new Set([
      ...diagnosis.items
        .filter(
          (item) => item.enhancement && ['queued', 'running'].includes(item.enhancement.status),
        )
        .map((item) => item.enhancement!.task_id),
      ...(submittedEnhancement ? [submittedEnhancement] : []),
    ]),
  ]
    .sort()
    .join(',');
  useEffect(() => {
    if (!enhancementTaskIds) return;
    const controller = new AbortController();
    setEnhancementPollError(undefined);
    const refresh = async (task: Task) => {
      const next = await api.diagnosis(initial.id, controller.signal);
      if (!controller.signal.aborted) {
        setDiagnosis(next);
        setLastSyncedAt(Date.now());
        if (task.id === submittedEnhancement && isTerminal(task.status))
          setSubmittedEnhancement('');
      }
    };
    void Promise.all(
      enhancementTaskIds
        .split(',')
        .map((taskId) => pollTask(api, taskId, refresh, controller.signal)),
    ).catch((error) => {
      if (!controller.signal.aborted) setEnhancementPollError(error);
    });
    return () => controller.abort();
  }, [initial.id, enhancementTaskIds, enhancementRevision]);
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
            model_id: null,
            profile: diagnosis.profile,
            jobs: diagnosis.items.map((i) => i.job),
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
      JSON.stringify([diagnosis.id]),
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
            className="button secondary report-export"
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
        <span>{diagnosis.model_id ? '历史分析' : '材料覆盖参考'}</span>
        <span>{new Date(diagnosis.created_at).toLocaleString('zh-CN')}</span>
      </div>
      {!terminal && (
        <DiagnosisProgress
          diagnosis={diagnosis}
          jobs={snapshots.data?.jobs || []}
          modelName={
            app.models.find((model) => model.id === diagnosis.model_id)?.display_name ||
            diagnosis.model_id ||
            '基础诊断'
          }
          lastSyncedAt={lastSyncedAt}
          disconnected={Boolean(pollError)}
          reconnect={() => setPollRevision((n) => n + 1)}
          viewItem={(id) => {
            selectItem(id);
            document.getElementById('job-report')?.focus();
          }}
        />
      )}
      {diagnosis.status === 'partial' && (
        <p className="notice warning">
          部分岗位尚未完成诊断。已有结果仍可查看和导出；可以基于同一份材料重新诊断。
        </p>
      )}
      {diagnosis.status === 'failed' && (
        <p className="notice error" role="alert">
          本次诊断没有可用评分。请查看逐岗位错误，再重试诊断。
        </p>
      )}
      <ErrorNotice error={pollError} />
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
            onClick={() => selectItem(item.id)}
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
              selectItem(next.id);
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
              {item.score_result
                ? item.score_result.scorable_weight_ratio === 0
                  ? '暂不可评分'
                  : item.score_result.score.toFixed(1)
                : '—'}
              <small>/ 100</small>
            </div>
            <div className="score-track">
              <span style={{ width: `${item.score_result?.score || 0}%` }} />
            </div>
            <p className="unknown-caption">
              还有多少没判断{' '}
              <strong>
                {item.score_result ? percent(item.score_result.unknown_weight_ratio) : '待计算'}
              </strong>
            </p>
          </button>
        ))}
      </div>
      <section id="job-report" role="tabpanel" tabIndex={-1} aria-labelledby={`tab-${selected.id}`}>
        {selected.report &&
          selected.status === 'succeeded' &&
          selected.report_template_version === 'base-report-v1' && (
            <EnhancementPanel
              key={selected.id}
              diagnosisId={diagnosis.id}
              item={selected}
              job={findJob(selected)}
              submitting={Boolean(submittedEnhancement)}
              pollError={enhancementPollError}
              onReconnect={() => setEnhancementRevision((n) => n + 1)}
              onStarted={setSubmittedEnhancement}
            />
          )}
        {selected.report && selected.report_template_version !== 'base-report-v1' && (
          <p className="notice">此为历史报告，可用当前材料重新生成基础报告后再获取建议。</p>
        )}
        <JobReport
          item={selected}
          job={findJob(selected)}
          profile={snapshots.data?.profile}
          diagnosisId={diagnosis.id}
        />
      </section>
      <ProfileVersionComparison
        current={diagnosis}
        item={selected}
        profile={snapshots.data?.profile}
        job={findJob(selected)}
        diagnosisIds={app.workspace.diagnosisIds}
        baselineId={params.get('before') || ''}
        onBaselineChange={(id) =>
          setParams(
            (previous) => {
              const next = new URLSearchParams(previous);
              if (id) next.set('before', id);
              else next.delete('before');
              next.set('job', selected.job.id);
              return next;
            },
            { replace: true },
          )
        }
      />
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">下一步</p>
            <h2>补充经历，或比较历史诊断</h2>
          </div>
          <Link className="text-link" to={`/profiles/${diagnosis.profile.id}`}>
            补充档案 →
          </Link>
        </div>
        <p>
          重新诊断使用本次诊断的材料与 JD 版本，不调用 AI 或修改历史报告。
          修改档案后，请到目标岗位页开始新诊断；个性化建议可在上方按需生成。
        </p>
        <div className="rerun">
          <button
            className="button"
            disabled={!terminal || action.busy || action.cooldown > 0}
            onClick={redo}
          >
            {action.busy
              ? '正在创建…'
              : action.cooldown
                ? `${action.cooldown} 秒后重试`
                : '用同一份材料再算一次'}
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
            <p>{e?.quote || '该证据尚未读取，请重新读取本次诊断使用的材料。'}</p>
            <cite>
              {e?.source_type === 'document' ? '简历原文' : '补充经历'}
              {e?.locator
                ? ` · ${e.locator.replace('paragraph:', '第 ').replace('page:', '页 ')}`
                : ''}
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
  diagnosisId,
}: {
  item: DiagnosisItem;
  job?: Job;
  profile?: Profile;
  diagnosisId?: string;
}) {
  const score = item.score_result;
  const hasAnalysis = Boolean(
    item.enhancement_history?.some((e) => ['succeeded', 'partial'].includes(e.status)) ||
      (item.enhancement && ['succeeded', 'partial'].includes(item.enhancement.status)),
  );
  const report = item.report;
  const evidence = profile?.content.evidence || [];
  const requirement = (id: string) => job?.content.requirements.find((r) => r.id === id);
  const supplementCount =
    score?.assessments.filter(
      (a) =>
        a.status !== 'met' && a.counted_in_score !== false && a.unknown_reason !== 'manual_review',
    ).length ?? 0;
  return (
    <>
      <nav className="report-section-nav" aria-label="报告栏目">
        <a href="#report-overview">概览</a>
        <a href="#report-requirements">条件核对</a>
        <a href="#report-insights">差距与计划</a>
        <a href="#rewrite-advice">修改建议</a>
        <a href="#ai-analysis">AI 分析</a>
      </nav>
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
      {item.status === 'reporting' && (
        <p className="notice">
          AI 报告尚未完成。已保存的自动评分与引用证据可以先查看，报告生成后会自动显示在这里。
        </p>
      )}
      {!score && ['pending', 'scoring'].includes(item.status) && (
        <p className="notice">该岗位尚未完成自动评分。可以先查看其他已完成岗位，或稍后回到本页。</p>
      )}
      {score && (
        <>
          <section className="panel">
            <div className="section-heading">
              <h2 id="report-overview">{hasAnalysis ? 'AI 分析概览' : '材料覆盖概览'}</h2>
            </div>
            {report && <p className="report-summary">{report.summary}</p>}
            <div className="dimensions">
              {score.dimensions.map((d) => (
                <div className="dimension" key={d.category}>
                  <div className="row">
                    <span>{labels[d.category]}</span>
                    <strong>
                      {score.assessments
                        .filter((a) => a.category === d.category)
                        .every((a) => a.counted_in_score === false)
                        ? '需要你自己判断'
                        : d.score.toFixed(1)}
                    </strong>
                  </div>
                  <div className="score-track">
                    <span style={{ width: `${d.score}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <p className="hint">
              {score.rule_version === 'coverage-v2'
                ? `自动评分范围占全部要求权重的 ${percent(score.scorable_weight_ratio ?? 1)}。需要你自己判断的项不计入分母；缺少证据和明确不满足的要求仍计入分母。此分数不代表全部条件已满足。`
                : '总分由后端按要求权重计算，不能直接平均类别分数。未知项仍计入分母。'}
            </p>
          </section>
          {supplementCount > 0 && profile && diagnosisId && (
            <p className="notice warning">
              <strong>还有 {supplementCount} 条影响分数，可在下方逐条补充。</strong>{' '}
              <button
                className="text-button"
                onClick={() => {
                  document
                    .querySelector('.requirement-follow-up')
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }}
              >
                定位第一条
              </button>
            </p>
          )}
          <section className="panel">
            <div className="section-heading">
              <h2 id="report-requirements">岗位条件核对</h2>
              <span className="count">{score.assessments.length}</span>
            </div>
            <div className="status-legend">
              {['met', 'partial', 'unmet', 'unknown'].map((s) => (
                <Status key={s} value={s} assessment />
              ))}
            </div>
            {score.assessments.map((a) => (
              <div className="assessment-entry" key={a.requirement_id}>
                <details className="assessment">
                  <summary>
                    <span className="assessment-title">
                      <small>
                        {a.requirement_id} · {labels[a.category]} · {labels[a.importance]}
                      </small>
                      <strong>{requirement(a.requirement_id)?.quote || a.requirement_id}</strong>
                    </span>
                    {a.unknown_reason ? (
                      <span className="badge status-unknown">
                        {
                          {
                            manual_review:
                              a.counted_in_score === false
                                ? '不参与评分，无需填写'
                                : '需要你自己判断',
                            unsupported_condition: '规则暂不支持',
                            conflicting_evidence: '证据有冲突',
                            missing_evidence: '缺少明确证据',
                          }[a.unknown_reason]
                        }
                      </span>
                    ) : (
                      <Status value={a.status} assessment />
                    )}
                  </summary>
                  <div className="assessment-body">
                    <p>{a.reason}</p>
                    {a.unknown_reason === 'manual_review' && a.counted_in_score === false && (
                      <p className="hint">
                        此项暂不参与自动评分：系统无法可靠判断是否满足。请自行核对，报告不会据此加减分。
                      </p>
                    )}
                    <p className="hint">
                      要求权重 {a.weight} · 覆盖系数 {a.coefficient} · 证据 {a.evidence_ids.length}{' '}
                      条
                    </p>
                    <EvidenceList ids={a.evidence_ids} evidence={evidence} />
                  </div>
                </details>
                {a.status !== 'met' &&
                  a.counted_in_score !== false &&
                  a.unknown_reason !== 'manual_review' &&
                  diagnosisId &&
                  profile && (
                    <Link
                      className="text-link requirement-follow-up"
                      aria-label={`补充要求 ${a.requirement_id} 的经历`}
                      to={`/profiles/${encodeURIComponent(profile.id)}/follow-up?diagnosis=${encodeURIComponent(diagnosisId)}&item=${encodeURIComponent(item.id)}&requirement=${encodeURIComponent(a.requirement_id)}`}
                    >
                      补充这项经历 →
                    </Link>
                  )}
              </div>
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
          <div className="report-columns" id="report-insights">
            <section className="panel">
              <p className="eyebrow">GAPS / 差距与证据</p>
              <h2>先分清差在哪里</h2>
              {!report.gaps.length && <p className="empty-inline">本报告未列出差距。</p>}
              {report.gaps.map((gap, i) => (
                <article className="gap" key={`${gap.requirement_id}-${i}`}>
                  <span
                    className={`badge status-${gap.kind === 'needs_evidence' ? 'unknown' : gap.kind === 'explicit_gap' ? 'unmet' : 'partial'}`}
                  >
                    {score?.assessments.find((a) => a.requirement_id === gap.requirement_id)
                      ?.counted_in_score === false
                      ? '需要你自己判断'
                      : labels[gap.kind]}
                  </span>
                  <h3>
                    {hasAnalysis
                      ? gap.description
                      : score?.assessments.find((a) => a.requirement_id === gap.requirement_id)
                          ?.reason || gap.description}
                  </h3>
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
              {!report.actions.length && (
                <p className="empty-inline">生成 AI 分析后，这里会列出具体的修改步骤与完成标准。</p>
              )}
              {report.actions.map((a, i) => (
                <article className="action-item" key={`${a.requirement_id}-${i}`}>
                  <div className="row">
                    <span className="tag">
                      {{ P0: '优先处理', P1: '建议完善', P2: '进一步提升' }[a.priority]}
                    </span>
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
          <ReportSuggestions
            selectionKey={item.id}
            suggestions={report.suggestions}
            renderEvidence={(ids) => <EvidenceList ids={ids} evidence={evidence} />}
          />
        </>
      )}
      {(item.enhancement_history?.length
        ? item.enhancement_history
        : item.enhancement
          ? [item.enhancement]
          : []
      )
        .filter((entry) => entry.model_metadata && ['succeeded', 'partial'].includes(entry.status))
        .map((entry) => (
          <details className="model-metadata" key={entry.task_id}>
            <summary>查看分析来源</summary>
            <strong>建议生成记录</strong>
            <span>
              {entry.model_metadata!.provider} / {entry.model_metadata!.model}
            </span>
            <span>
              {entry.model_metadata!.model_id} · 目标要求：{entry.requirement_ids.join('、')}
            </span>
            <small>
              生成于 {new Date(entry.model_metadata!.generated_at).toLocaleString('zh-CN')}
            </small>
          </details>
        ))}
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
            <p className="notice success">两份报告使用相同的材料与 JD 版本。</p>
            <div className="table-scroll">
              <table>
                <caption>不同模型的独立岗位评分</caption>
                <thead>
                  <tr>
                    <th>岗位</th>
                    <th>{current.model_id || '基础报告'}（当前）</th>
                    <th>{other.data.model_id || '基础报告'}（历史）</th>
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
              阅读历史报告 →
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
    { keepPreviousData: true },
  );
  const hasRunning = load.data?.some(
    (entry) =>
      entry.status === 'fulfilled' &&
      (!isTerminal(entry.value.status) ||
        entry.value.items.some(
          (item) => item.enhancement && ['queued', 'running'].includes(item.enhancement.status),
        )),
  );
  useEffect(() => {
    if (!hasRunning) return;
    const timer = setInterval(() => {
      if (!document.hidden) load.reload();
    }, 5000);
    return () => clearInterval(timer);
  }, [hasRunning]);
  return (
    <>
      <Heading eyebrow="04 / 历史记录" title="每一次诊断，都留有依据">
        此处记录当前标签页访问过的诊断。已保存的报告链接可在有效会话内重新读取。
      </Heading>
      {hasRunning && (
        <p className="notice" role="status">
          有诊断仍在后台进行，本列表会自动更新。可以离开此页，稍后打开记录继续查看。
        </p>
      )}
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
                    <p>
                      {entry.value.model_id
                        ? `历史任务模型：${entry.value.model_id}`
                        : '基础报告 · 程序生成'}
                    </p>
                    <p>
                      已处理{' '}
                      {
                        entry.value.items.filter((item) =>
                          ['succeeded', 'score_only', 'failed'].includes(item.status),
                        ).length
                      }{' '}
                      / {entry.value.items.length} 个岗位 · 已生成{' '}
                      {entry.value.items.filter((item) => item.report !== null).length} 份报告
                    </p>
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
