import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useLoad } from '../hooks';
import {
  compareProfileVersions,
  type ProfileComparison,
  type RequirementChange,
} from '../lib/profileComparison';
import type { Diagnosis, DiagnosisItem, Job, Profile } from '../types';
import { ErrorNotice, Loading, Status } from './ui';

type Props = {
  current: Diagnosis;
  item: DiagnosisItem;
  profile?: Profile;
  job?: Job;
  diagnosisIds: string[];
  baselineId: string;
  onBaselineChange: (id: string) => void;
};
const percent = (ratio: number) => `${(ratio * 100).toFixed(2)}%`;
const signed = (value: number, digits: number) => `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;

export function ProfileVersionComparison(props: Props) {
  const headingId = useId();
  const candidates = [...new Set([...props.diagnosisIds, props.baselineId])].filter(
    (id) => id && id !== props.current.id,
  );
  return (
    <section className="panel profile-comparison" aria-labelledby={headingId}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">CHANGES / 档案版本变化</p>
          <h2 id={headingId}>同一岗位，补充前后发生了什么</h2>
        </div>
      </div>
      <p className="hint">
        仅比较同一档案的不同确认版本，并保持
        JD、评分规则与匹配器版本一致。这里展示已保存的评分和证据，不重新打分。
      </p>
      {candidates.length > 0 && (
        <label className="field compare-picker">
          选择另一份诊断查看档案变化
          <select
            value={props.baselineId}
            onChange={(event) => props.onBaselineChange(event.target.value)}
          >
            <option value="">选择另一份诊断</option>
            {candidates.map((id) => (
              <option value={id} key={id}>
                诊断 {id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      {!props.baselineId ? (
        <p className="empty-inline">
          补充并确认新档案后，使用同一岗位版本生成诊断，再选择前后两份报告。下方仍可比较历史诊断。
        </p>
      ) : props.baselineId === props.current.id ? (
        <p className="notice warning">请选择另一份诊断，当前报告不能与自身比较。</p>
      ) : (
        <ComparisonLoader
          key={`${props.current.id}:${props.item.id}:${props.baselineId}`}
          {...props}
        />
      )}
    </section>
  );
}

function ComparisonLoader({ current, item, profile, job, baselineId }: Props) {
  const load = useLoad(async (signal) => {
    const baseline = await api.diagnosis(baselineId, signal);
    const baselineProfile = await api.profile(
      baseline.profile.id,
      baseline.profile.version,
      signal,
    );
    return { baseline, baselineProfile };
  }, baselineId);
  if (load.error) return <ErrorNotice error={load.error} retry={load.reload} />;
  if (load.loading || !load.data || !profile || !job)
    return <Loading text="正在读取两份报告的冻结档案与岗位…" />;
  const comparison = compareProfileVersions({
    current,
    currentItem: item,
    currentProfile: profile,
    job,
    baseline: load.data.baseline,
    baselineProfile: load.data.baselineProfile,
  });
  return comparison.comparable ? (
    <ComparisonDetails comparison={comparison} />
  ) : (
    <p className="notice warning">{comparison.reason}</p>
  );
}

function ComparisonDetails({
  comparison,
}: {
  comparison: Extract<ProfileComparison, { comparable: true }>;
}) {
  const [onlyChanged, setOnlyChanged] = useState(false);
  const { before, after, rows, job } = comparison;
  const changedCount = rows.filter((row) => row.changed).length;
  const shown = onlyChanged ? rows.filter((row) => row.changed) : rows;
  return (
    <>
      <p>
        <strong>{job.content.title}</strong> · JD v{job.version} · {after.score.rule_version} /{' '}
        {after.score.matcher_version}
      </p>
      <div className="form-grid profile-comparison-versions">
        {[before, after].map((snapshot, index) => (
          <div key={snapshot.diagnosis.id}>
            <h3>
              {index === 0 ? '较早' : '较新'}档案 v{snapshot.profile.version}
            </h3>
            <p className="hint">
              资料截止 {snapshot.profile.content.as_of_month} · 报告模型{' '}
              {snapshot.diagnosis.model_id}
            </p>
            <Link
              className="text-link"
              to={`/diagnoses/${encodeURIComponent(snapshot.diagnosis.id)}?before=${encodeURIComponent(index === 0 ? after.diagnosis.id : before.diagnosis.id)}&job=${encodeURIComponent(job.id)}`}
            >
              打开{index === 0 ? '较早' : '较新'}档案的完整报告 →
            </Link>
          </div>
        ))}
      </div>
      <div className="form-grid profile-comparison-summary">
        <div>
          <h3>材料覆盖分</h3>
          <p>
            {before.score.score.toFixed(1)} → {after.score.score.toFixed(1)} / 100
          </p>
          <strong>变化 {signed(comparison.scoreChange, 1)} 分</strong>
        </div>
        <div>
          <h3>未知权重比例</h3>
          <p>
            {percent(before.score.unknown_weight_ratio)} →{' '}
            {percent(after.score.unknown_weight_ratio)}
          </p>
          <strong>变化 {signed(comparison.unknownPercentagePointChange, 2)} 个百分点</strong>
        </div>
      </div>
      {comparison.cutoffChanged && (
        <p className="notice warning">
          两个版本的资料截止月份不同。未结束经历的累计月数可能因此变化，不能将全部评分变化归因于补充材料。
        </p>
      )}
      <p className="hint">
        变化不等于能力提升；明确否认也会让缺少证据变为明确不满足。新增引用不一定是新材料，复制建议本身不会改变评分。
      </p>
      <div className="profile-comparison-filters">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyChanged}
            onChange={(event) => setOnlyChanged(event.target.checked)}
          />
          只看有变化的要求
        </label>
        <p className="hint">
          {changedCount} / {rows.length} 条要求的状态、理由或引用发生变化。
        </p>
      </div>
      {!shown.length && <p className="empty-inline">没有状态、理由或引用发生变化的要求。</p>}
      {shown.map((row) => (
        <details className="assessment profile-comparison-row" key={row.requirement.id}>
          <summary>
            <span className="assessment-title">
              <small>
                {row.requirement.id} · {row.changed ? '有变化' : '未变化'}
              </small>
              <strong>{row.requirement.quote}</strong>
            </span>
            <span className="profile-comparison-statuses">
              <Status value={row.before.status} assessment /> →{' '}
              <Status value={row.after.status} assessment />
            </span>
          </summary>
          <div className="assessment-body form-grid profile-comparison-evidence">
            <ComparisonEvidence row={row} side="before" version={before.profile.version} />
            <ComparisonEvidence row={row} side="after" version={after.profile.version} />
          </div>
        </details>
      ))}
    </>
  );
}

function ComparisonEvidence({
  row,
  side,
  version,
}: {
  row: RequirementChange;
  side: 'before' | 'after';
  version: number;
}) {
  const citations = side === 'before' ? row.beforeEvidence : row.afterEvidence;
  return (
    <section aria-label={`${row.requirement.id} 档案 v${version} 的证据`}>
      <h4>档案 v{version}</h4>
      <p>{row[side].reason}</p>
      {!citations.length && <p className="hint">本版本未引用证据；不据此断言没有能力。</p>}
      {citations.map((evidence) => (
        <blockquote key={evidence.id}>
          {row.changedReferences.includes(evidence.id) ? (
            <small>同一引用的内容有变化</small>
          ) : side === 'after' && row.addedReferences.includes(evidence.id) ? (
            <small>本次新增引用</small>
          ) : side === 'before' && row.removedReferences.includes(evidence.id) ? (
            <small>本次不再引用</small>
          ) : null}
          <p>{evidence.quote}</p>
          <cite>
            {evidence.id} · {evidence.source_type} · {evidence.source_id}
            {evidence.locator ? ` · ${evidence.locator}` : ''}
          </cite>
        </blockquote>
      ))}
    </section>
  );
}
