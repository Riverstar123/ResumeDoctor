import type {
  Diagnosis,
  DiagnosisItem,
  Evidence,
  Job,
  Profile,
  Requirement,
  Schema,
} from '../types';
import { confirmedCoverage } from './reportCoverage';

type Assessment = Schema['RequirementAssessment'];
type Snapshot = {
  diagnosis: Diagnosis;
  item: DiagnosisItem;
  profile: Profile;
  score: Schema['ScoreResult'];
};
export type RequirementChange = {
  requirement: Requirement;
  before: Assessment;
  after: Assessment;
  beforeEvidence: Evidence[];
  afterEvidence: Evidence[];
  addedReferences: string[];
  removedReferences: string[];
  changedReferences: string[];
  changed: boolean;
};
export type ProfileComparison =
  | { comparable: false; reason: string }
  | {
      comparable: true;
      before: Snapshot;
      after: Snapshot;
      job: Job;
      scoreChange: number;
      unknownPercentagePointChange: number;
      cutoffChanged: boolean;
      rows: RequirementChange[];
    };

const sameVersion = (a: { id: string; version: number }, b: { id: string; version: number }) =>
  a.id === b.id && a.version === b.version;
const evidenceContent = (e: Evidence) =>
  JSON.stringify([e.source_type, e.source_id, e.quote, e.locator]);
const unavailable = (reason: string): ProfileComparison => ({ comparable: false, reason });

/** Compare the confirmed coverage of saved assessment rows. */
export function compareProfileVersions({
  current,
  currentItem,
  currentProfile,
  job,
  baseline,
  baselineProfile,
}: {
  current: Diagnosis;
  currentItem: DiagnosisItem;
  currentProfile: Profile;
  job: Job;
  baseline: Diagnosis;
  baselineProfile: Profile;
}): ProfileComparison {
  if (current.profile.id !== baseline.profile.id)
    return unavailable('两份诊断属于不同档案，不能作为同一档案的前后变化。');
  if (current.profile.version === baseline.profile.version)
    return unavailable(
      '两份诊断使用同一档案版本。请使用下方的同材料模型比较，或选择不同档案版本。',
    );
  if (
    !sameVersion(currentProfile, current.profile) ||
    !sameVersion(baselineProfile, baseline.profile)
  )
    return unavailable('档案版本与报告不一致，请重新读取报告。');
  if (!currentProfile.confirmed || !baselineProfile.confirmed)
    return unavailable('仅能比较两个已确认的档案版本。');
  if (
    !current.items.some(
      (item) => item.id === currentItem.id && sameVersion(item.job, currentItem.job),
    )
  )
    return unavailable('当前岗位与诊断不一致，请重新选择岗位。');
  if (!sameVersion(job, currentItem.job) || !job.confirmed)
    return unavailable('尚未读取当前岗位的已确认版本。');
  const baselineItem = baseline.items.find((item) => sameVersion(item.job, currentItem.job));
  if (!baselineItem)
    return unavailable('另一份诊断没有相同的 JD 版本，不能将岗位要求变化归为档案改进。');
  const currentScore = currentItem.score_result;
  const baselineScore = baselineItem.score_result;
  if (!currentScore || !baselineScore)
    return unavailable('两侧均须已有保存的自动评分；AI 报告未完成不影响已有评分的比较。');
  if (
    !currentScore.rule_version ||
    !currentScore.matcher_version ||
    currentScore.rule_version !== baselineScore.rule_version ||
    currentScore.matcher_version !== baselineScore.matcher_version
  )
    return unavailable('两份评分的规则或匹配器版本不同，不能直接比较档案变化。');

  const currentSnapshot: Snapshot = {
    diagnosis: current,
    item: currentItem,
    profile: currentProfile,
    score: currentScore,
  };
  const baselineSnapshot: Snapshot = {
    diagnosis: baseline,
    item: baselineItem,
    profile: baselineProfile,
    score: baselineScore,
  };
  const [before, after] =
    current.profile.version < baseline.profile.version
      ? [currentSnapshot, baselineSnapshot]
      : [baselineSnapshot, currentSnapshot];
  const requirements = job.content.requirements.filter((requirement) => !requirement.ignored);
  const beforeAssessments = new Map(before.score.assessments.map((a) => [a.requirement_id, a]));
  const afterAssessments = new Map(after.score.assessments.map((a) => [a.requirement_id, a]));
  const complete = (assessments: Map<string, Assessment>, source: Assessment[]) =>
    assessments.size === source.length &&
    assessments.size === requirements.length &&
    requirements.every((requirement) => {
      const assessment = assessments.get(requirement.id);
      return (
        assessment?.category === requirement.category &&
        assessment.importance === requirement.importance
      );
    });
  if (
    !complete(beforeAssessments, before.score.assessments) ||
    !complete(afterAssessments, after.score.assessments)
  )
    return unavailable('评分中的要求与本次使用的 JD 不一致，无法可靠地逐条比较。');
  const beforeEvidence = new Map(before.profile.content.evidence.map((e) => [e.id, e]));
  const afterEvidence = new Map(after.profile.content.evidence.map((e) => [e.id, e]));
  if (
    before.score.assessments.some((a) => a.evidence_ids.some((id) => !beforeEvidence.has(id))) ||
    after.score.assessments.some((a) => a.evidence_ids.some((id) => !afterEvidence.has(id)))
  )
    return unavailable(
      '评分引用的证据未能在在本次诊断的材料中找到，请重新读取；不会借用其他版本的证据。',
    );
  const rows = requirements.map((requirement): RequirementChange => {
    const oldAssessment = beforeAssessments.get(requirement.id)!;
    const newAssessment = afterAssessments.get(requirement.id)!;
    const addedReferences = newAssessment.evidence_ids.filter(
      (id) => !oldAssessment.evidence_ids.includes(id),
    );
    const removedReferences = oldAssessment.evidence_ids.filter(
      (id) => !newAssessment.evidence_ids.includes(id),
    );
    const changedReferences = newAssessment.evidence_ids.filter(
      (id) =>
        oldAssessment.evidence_ids.includes(id) &&
        evidenceContent(beforeEvidence.get(id)!) !== evidenceContent(afterEvidence.get(id)!),
    );
    return {
      requirement,
      before: oldAssessment,
      after: newAssessment,
      beforeEvidence: oldAssessment.evidence_ids.map((id) => beforeEvidence.get(id)!),
      afterEvidence: newAssessment.evidence_ids.map((id) => afterEvidence.get(id)!),
      addedReferences,
      removedReferences,
      changedReferences,
      changed:
        oldAssessment.status !== newAssessment.status ||
        oldAssessment.coefficient !== newAssessment.coefficient ||
        oldAssessment.reason !== newAssessment.reason ||
        Boolean(addedReferences.length || removedReferences.length || changedReferences.length),
    };
  });
  return {
    comparable: true,
    before,
    after,
    job,
    scoreChange: Number(
      (confirmedCoverage(after.score) - confirmedCoverage(before.score)).toFixed(1),
    ),
    unknownPercentagePointChange: Number(
      ((after.score.unknown_weight_ratio - before.score.unknown_weight_ratio) * 100).toFixed(2),
    ),
    cutoffChanged: before.profile.content.as_of_month !== after.profile.content.as_of_month,
    rows,
  };
}
