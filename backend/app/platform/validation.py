"""M2 snapshot guards. Real extraction/matching/report validation stays with C/D/E."""

from app.contracts import JobContent, ProfileContent, ScoreResult
from app.platform.errors import PlatformError


def invalid() -> PlatformError:
    return PlatformError(422, "VALIDATION_ERROR", "资料内容或证据引用不合法")


def validate_profile(content: ProfileContent, current_month: str) -> None:
    facts = [f.id for f in content.facts]
    evidence = [e.id for e in content.evidence]
    if len(set(facts)) != len(facts) or len(set(evidence)) != len(evidence):
        raise invalid()
    if content.as_of_month > current_month:
        raise invalid()
    for fact in content.facts:
        if not set(fact.evidence_ids) <= set(evidence):
            raise invalid()
        if fact.kind == "education" and fact.value not in {
            "associate",
            "bachelor",
            "master",
            "doctorate",
            "other",
            None,
        }:
            raise invalid()
        if fact.start_month and fact.end_month and fact.start_month > fact.end_month:
            raise invalid()
        if fact.end_month and fact.end_month > content.as_of_month:
            raise invalid()


def validate_job(content: JobContent, raw_text: str) -> None:
    ids = [r.id for r in content.requirements]
    if not raw_text.strip() or len(set(ids)) != len(ids):
        raise invalid()
    for requirement in content.requirements:
        if requirement.quote not in raw_text:
            raise invalid()
        if requirement.ignored and not (requirement.ignore_reason or "").strip():
            raise invalid()
        if requirement.operator == "min_months":
            if not requirement.target.isascii() or not requirement.target.isdecimal():
                raise invalid()
            try:
                months = int(requirement.target)
            except ValueError:
                # Python's integer digit limit is an input error, not an internal failure.
                raise invalid() from None
            if months < 1 or not (requirement.subject or "").strip():
                raise invalid()
        elif requirement.subject is not None:
            raise invalid()
        if requirement.operator == "degree_at_least" and requirement.target not in {
            "associate",
            "bachelor",
            "master",
            "doctorate",
        }:
            raise invalid()


def validate_score(score: ScoreResult, profile: ProfileContent, job: JobContent) -> None:
    """Guard references/state fields before saving; M4 still owns computation."""
    requirements = {r.id: r for r in job.requirements if not r.ignored}
    ids = [a.requirement_id for a in score.assessments]
    evidence = {e.id for e in profile.evidence}
    if (
        len(set(ids)) != len(ids)
        or set(ids) != set(requirements)
        or score.rule_version != "coverage-v1"
        or score.matcher_version != "matcher-v1"
    ):
        raise PlatformError(422, "MODEL_OUTPUT_INVALID", "评分引用或版本不合法")
    for assessment in score.assessments:
        requirement = requirements[assessment.requirement_id]
        if (
            not set(assessment.evidence_ids) <= evidence
            or assessment.category != requirement.category
            or assessment.importance != requirement.importance
            or assessment.weight != (2 if requirement.importance == "must" else 1)
            or assessment.coefficient
            != {"met": 1, "partial": 0.5, "unmet": 0, "unknown": 0}[assessment.status]
        ):
            raise PlatformError(422, "MODEL_OUTPUT_INVALID", "评分状态或证据不合法")
