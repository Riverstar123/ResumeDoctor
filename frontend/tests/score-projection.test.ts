// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { projectedScore } from '../src/lib/scoreProjection';
import type { ScoreResult } from '../src/types';

function score(
  assessments: Array<{
    status: string;
    weight: number;
    coefficient: number;
    counted?: boolean;
  }>,
  value = 50,
): ScoreResult {
  return {
    score: value,
    unknown_weight_ratio: 0.25,
    scorable_weight_ratio: 1,
    rule_version: 'coverage-v3',
    matcher_version: 'matcher-v3',
    assessments: assessments.map((item, index) => ({
      requirement_id: `r${index + 1}`,
      category: 'skill',
      importance: 'must',
      status: item.status,
      weight: item.weight,
      coefficient: item.coefficient,
      evidence_ids: [],
      reason: 'test',
      unknown_reason: item.status === 'met' ? null : 'missing_evidence',
      counted_in_score: item.counted ?? true,
    })),
    dimensions: [],
  } as unknown as ScoreResult;
}

describe('projectedScore', () => {
  it('adds the full weight of a missing requirement', () => {
    expect(
      projectedScore(
        score(
          [
            { status: 'met', weight: 2, coefficient: 1 },
            { status: 'unknown', weight: 2, coefficient: 0 },
          ],
          25,
        ),
      ),
    ).toBe(75);
  });

  it('adds only the missing half of a partial requirement', () => {
    expect(
      projectedScore(
        score([
          { status: 'met', weight: 2, coefficient: 1 },
          { status: 'partial', weight: 2, coefficient: 0.5 },
        ]),
      ),
    ).toBe(75);
  });

  it('ignores manual-review items that do not count toward the score', () => {
    expect(
      projectedScore(
        score([
          { status: 'met', weight: 2, coefficient: 1 },
          { status: 'unknown', weight: 2, coefficient: 0, counted: false },
        ]),
      ),
    ).toBe(50);
  });

  it('never exceeds 100', () => {
    expect(
      projectedScore(
        score(
          [
            { status: 'met', weight: 1, coefficient: 1 },
            { status: 'unknown', weight: 1, coefficient: 0 },
          ],
          99.9,
        ),
      ),
    ).toBe(100);
  });
});
