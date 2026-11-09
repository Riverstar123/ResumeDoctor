import type { Schema } from '../types';

/** Read the confirmed share of all requirements from the frozen assessment rows. */
export function confirmedCoverage(
  score: Schema['ScoreResult'],
  category?: Schema['DimensionScore']['category'],
): number {
  const rows = category
    ? score.assessments.filter((row) => row.category === category)
    : score.assessments;
  if (!category && rows.every((row) => row.counted_in_score !== false)) return score.score;
  const weight = rows.reduce((sum, row) => sum + row.weight, 0);
  const covered = rows.reduce((sum, row) => sum + row.weight * row.coefficient, 0);
  return weight ? Math.round((1000 * covered) / weight) / 10 : 0;
}

export function originalScoreContext(score?: Schema['ScoreResult'] | null): string | undefined {
  if (!score?.assessments.some((row) => row.counted_in_score === false)) return undefined;
  const automatic = score.assessments.some((row) => row.counted_in_score !== false)
    ? `原报告使用自动评分 ${score.score.toFixed(1)} / 100，分母只含可自动计分的条件。`
    : '原报告的自动评分范围为空。';
  return `${automatic}已证实覆盖分按全部有效条件计算。`;
}
