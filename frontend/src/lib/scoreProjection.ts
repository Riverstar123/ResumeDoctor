import type { ScoreResult } from '../types';

/**
 * Upper bound if every scored, non-met requirement became fully met.
 * This is a display-only estimate; it never changes the frozen score.
 */
export function projectedScore(score: ScoreResult): number | null {
  const counted = score.assessments.filter((item) => item.counted_in_score !== false);
  const total = counted.reduce((sum, item) => sum + item.weight, 0);
  if (!total) return null;
  const gain = counted.reduce((sum, item) => {
    if (item.status === 'met') return sum;
    return sum + item.weight * (1 - item.coefficient);
  }, 0);
  return Math.min(100, Math.round((score.score + (gain / total) * 100) * 10) / 10);
}
