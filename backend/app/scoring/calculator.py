"""coverage-v1: Decimal arithmetic over validated, already filtered assessments."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

from app.contracts import DimensionScore, RequirementAssessment, ScoreResult

from .errors import ScoringError

RULE_VERSION = "coverage-v1"
MATCHER_VERSION = "matcher-v1"
WEIGHTS = {"must": 2, "preferred": 1}
COEFFICIENTS = {
    "met": Decimal("1"),
    "partial": Decimal("0.5"),
    "unmet": Decimal("0"),
    "unknown": Decimal("0"),
}


def _percentage(items: Sequence[RequirementAssessment]) -> float:
    denominator = sum(item.weight for item in items)
    numerator = sum((item.weight * COEFFICIENTS[item.status] for item in items), Decimal(0))
    return float((100 * numerator / denominator).quantize(Decimal("0.1"), ROUND_HALF_UP))


def calculate_score(
    assessments: Sequence[RequirementAssessment], rule_version: str = RULE_VERSION
) -> ScoreResult:
    """Do not repair inconsistent caller states or mutate the supplied DTOs.

    Only matcher-v1 is supported in this release, so its version is unambiguous.
    Ignored requirements must be excluded by the matcher before this call.
    """
    if rule_version != RULE_VERSION:
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
        item.evidence_ids.sort()
    items.sort(key=lambda item: item.requirement_id)
    by_category: dict[str, list[RequirementAssessment]] = defaultdict(list)
    for item in items:
        by_category[item.category].append(item)
    total = sum(item.weight for item in items)
    unknown = sum(item.weight for item in items if item.status == "unknown")
    return ScoreResult(
        score=_percentage(items),
        unknown_weight_ratio=float(
            (Decimal(unknown) / total).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        ),
        rule_version=RULE_VERSION,
        matcher_version=MATCHER_VERSION,
        assessments=items,
        dimensions=[
            DimensionScore(category=category, score=_percentage(group))
            for category, group in sorted(by_category.items())
        ],
    )
