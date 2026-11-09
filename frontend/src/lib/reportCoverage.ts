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
