"""QA harness, not the M5 implementation. E can feed its actual outputs here."""

import re

from app.contracts import DiagnosisItem, JobContent, ProfileContent, ScoreResult
from app.scoring import assess_requirements, calculate_score


class ReportContractError(ValueError):
    pass


def _score_semantics(score: ScoreResult) -> dict:
    # Historical reason wording is not a new score. Mutable score checking below is exact.
    return dict(
        score=score.score,
        unknown_weight_ratio=score.unknown_weight_ratio,
        rule_version=score.rule_version,
        matcher_version=score.matcher_version,
        dimensions={d.category: d.score for d in score.dimensions},
        assessments={
            a.requirement_id: dict(
                category=a.category,
                importance=a.importance,
                status=a.status,
                weight=a.weight,
                coefficient=a.coefficient,
                evidence_ids=sorted(a.evidence_ids),
            )
            for a in score.assessments
        },
    )


def check_report_contract(
    profile: ProfileContent,
    job: JobContent,
    item: DiagnosisItem,
    *,
    expected_score: ScoreResult | None = None,
    expected_model_id: str | None = None,
) -> None:
    """Raise on references/statuses/score drift or unsupported numeric rewrites.

    Number checking is conservative: technical numbers also require supporting
    evidence or placeholders. It cannot replace M5's semantic fact validation.
    """
    score = item.score_result
    if score is None:
        raise ReportContractError("final item must contain a score")
    if expected_score is not None and score.model_dump() != expected_score.model_dump():
        raise ReportContractError("reporting mutated frozen ScoreResult")
    expected = calculate_score(assess_requirements(profile, job))
    if _score_semantics(score) != _score_semantics(expected):
        raise ReportContractError("score differs from deterministic snapshot result")
    if len({d.category for d in score.dimensions}) != len(score.dimensions):
        raise ReportContractError("duplicate score dimensions")
    if len({a.requirement_id for a in score.assessments}) != len(score.assessments):
        raise ReportContractError("duplicate assessments")
    if item.status == "score_only":
        if item.report is not None:
            raise ReportContractError("score_only must not contain a report")
        return
    if item.status != "succeeded" or item.report is None or item.model_metadata is None:
        raise ReportContractError("successful item needs report and model metadata")
    if expected_model_id is not None and item.model_metadata.model_id != expected_model_id:
        raise ReportContractError("report used a different model selection")
    assessments = {a.requirement_id: a for a in score.assessments}
    evidence = {e.id: e for e in profile.evidence}
    gap_kinds = {"unmet": "explicit_gap", "partial": "partial_gap", "unknown": "needs_evidence"}
    seen_gaps = set()
    for collection in (item.report.gaps, item.report.suggestions, item.report.actions):
        for entry in collection:
            if entry.requirement_id not in assessments:
                raise ReportContractError("report references an unscored requirement")
            ids = getattr(entry, "evidence_ids", [])
            if set(ids) - set(evidence) or set(ids) - set(
                assessments[entry.requirement_id].evidence_ids
            ):
                raise ReportContractError(
                    "report evidence is missing or belongs to another requirement"
                )
    for gap in item.report.gaps:
        if gap.kind != gap_kinds.get(assessments[gap.requirement_id].status):
            raise ReportContractError("gap kind contradicts assessment status")
        if gap.requirement_id in seen_gaps:
            raise ReportContractError("duplicate gap")
        seen_gaps.add(gap.requirement_id)
    if any(
        a.importance == "must" and a.status != "met" and a.requirement_id not in seen_gaps
        for a in score.assessments
    ):
        raise ReportContractError("mandatory gap omitted")
    for suggestion in item.report.suggestions:
        if (
            not suggestion.evidence_ids or suggestion.original is None
        ) and not suggestion.requires_user_input:
            raise ReportContractError("unsupported rewrite must request user input")
        supported_numbers = {
            number
            for id in suggestion.evidence_ids
            for number in re.findall(r"\d+(?:\.\d+)?%?", evidence[id].quote)
        }
        revised = re.sub(r"\[[^\]]*\]", "", suggestion.revised)
        if set(re.findall(r"\d+(?:\.\d+)?%?", revised)) - supported_numbers:
            raise ReportContractError(
                "new concrete numbers lack evidence; use user-fill placeholders"
            )
