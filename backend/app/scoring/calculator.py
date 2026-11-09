"""Versioned coverage scores over validated, already filtered assessments."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

from app.contracts import DimensionScore, RequirementAssessment, ScoreResult

from .errors import ScoringError

RULE_VERSION = "coverage-v1"
MATCHER_VERSION = "matcher-v1"
CURRENT_RULE_VERSION = "coverage-v3"
CURRENT_MATCHER_VERSION = "matcher-v3"
WEIGHTS = {"must": 2, "preferred": 1}
COEFFICIENTS = {
    "met": Decimal("1"),
    "partial": Decimal("0.5"),
    "unmet": Decimal("0"),
    "unknown": Decimal("0"),
}


def coverage_percentage(items: Sequence[RequirementAssessment]) -> float:
    """Compute coverage over exactly the supplied assessment weights."""
    denominator = sum(item.weight for item in items)
    if not denominator:
        return 0.0
    numerator = sum((item.weight * COEFFICIENTS[item.status] for item in items), Decimal(0))
    return float((100 * numerator / denominator).quantize(Decimal("0.1"), ROUND_HALF_UP))


def calculate_score(
    assessments: Sequence[RequirementAssessment], rule_version: str = RULE_VERSION
) -> ScoreResult:
    """Do not repair inconsistent caller states or mutate the supplied DTOs.

    Each coverage version has a corresponding deterministic matcher version.
    Ignored requirements must be excluded by the matcher before this call.
    """
    if rule_version not in {RULE_VERSION, "coverage-v2", CURRENT_RULE_VERSION}:
        raise ScoringError("UNSUPPORTED_RULE_VERSION", f"Unsupported rule version: {rule_version}")
    if not assessments:
        raise ScoringError("NO_SCORABLE_REQUIREMENTS", "没有可评分要求，请修改岗位要求。")
    items = [RequirementAssessment.model_validate(item.model_dump()) for item in assessments]
    ids = [item.requirement_id for item in items]
    if any(not value.strip() for value in ids) or len(ids) != len(set(ids)):
        raise ScoringError("INVALID_SCORING_INPUT", "要求 ID 必须非空且唯一，不能重复加权。")
    for item in items:
        if (
            item.weight != WEIGHTS[item.importance]
            or Decimal(str(item.coefficient)) != (COEFFICIENTS[item.status])
        ):
            raise ScoringError(
                "INVALID_SCORING_INPUT", f"权重或系数与状态不一致：{item.requirement_id}"
            )
        if not item.counted_in_score and (
            rule_version == RULE_VERSION
            or item.status != "unknown"
            or item.unknown_reason not in {"manual_review", "unsupported_condition"}
        ):
            raise ScoringError("INVALID_SCORING_INPUT", "不能任意排除缺证据或未满足的要求。")
        item.evidence_ids.sort()
    items.sort(key=lambda item: item.requirement_id)
    by_category: dict[str, list[RequirementAssessment]] = defaultdict(list)
    for item in items:
        by_category[item.category].append(item)
    total = sum(item.weight for item in items)
    unknown = sum(item.weight for item in items if item.status == "unknown")
    counted = [item for item in items if item.counted_in_score]
    return ScoreResult(
        score=coverage_percentage(counted),
        unknown_weight_ratio=float(
            (Decimal(unknown) / total).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        ),
        rule_version=rule_version,
        matcher_version={
            "coverage-v1": MATCHER_VERSION,
            "coverage-v2": "matcher-v2",
            CURRENT_RULE_VERSION: CURRENT_MATCHER_VERSION,
        }[rule_version],
        scorable_weight_ratio=float(
            (Decimal(sum(a.weight for a in counted)) / total).quantize(
                Decimal("0.0001"), ROUND_HALF_UP
            )
        ),
        assessments=items,
        dimensions=[
            DimensionScore(
                category=category,
                score=coverage_percentage([item for item in group if item.counted_in_score]),
            )
            for category, group in sorted(by_category.items())
        ],
    )
