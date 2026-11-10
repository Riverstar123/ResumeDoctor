"""M2 snapshot guards. Real extraction/matching/report validation stays with C/D/E."""

from app.contracts import JobContent, ProfileContent, RequirementVerification, ScoreResult
from app.platform.errors import PlatformError, ProfileValidationError
from app.profile_dates import invalid_future_end
from app.structured_fields import validate_attributes, validate_condition


def invalid() -> PlatformError:
    return PlatformError(422, "VALIDATION_ERROR", "资料内容或证据引用不合法")


def validate_profile(content: ProfileContent, current_month: str) -> None:
    facts = [f.id for f in content.facts]
    evidence = [e.id for e in content.evidence]
    if len(set(facts)) != len(facts) or len(set(evidence)) != len(evidence):
        raise ProfileValidationError("REFERENCE_INVALID", "事实或证据编号重复，请核对后保存")
    if content.as_of_month > current_month:
        raise ProfileValidationError("PROFILE_DATE_INVALID", "档案截止月份不能晚于当前月份")
    for fact in content.facts:
        try:
            validate_attributes(
                fact,
                [e.quote for e in content.evidence if e.id in fact.evidence_ids],
                evidence=[e for e in content.evidence if e.id in fact.evidence_ids],
            )
        except ValueError as error:
            raise ProfileValidationError("SCHEMA_INVALID", str(error)) from None
        if not set(fact.evidence_ids) <= set(evidence):
            raise ProfileValidationError("REFERENCE_INVALID", "事实引用了不存在的证据，请重新关联")
        if fact.kind == "education" and fact.value not in {
            "associate",
            "bachelor",
            "master",
            "doctorate",
            "other",
            None,
        }:
            raise ProfileValidationError("SCHEMA_INVALID", "学历类型不合法，请选择明确的学历类型")
        if fact.start_month and fact.end_month and fact.start_month > fact.end_month:
            raise ProfileValidationError("PROFILE_DATE_INVALID", "开始月份不能晚于结束月份")
        if invalid_future_end(fact, content.as_of_month):
            raise ProfileValidationError(
                "FUTURE_END_DATE",
                "结束月份晚于档案截止月份；仅已开始的在读教育可填写预计毕业月份，请核对完成状态",
            )


def validate_profile_sources(
    content: ProfileContent, previous: ProfileContent | None = None
) -> None:
    """Guard human writes; only M3 may introduce verified document/message evidence.

    Existing nonmanual evidence is a trusted immutable record, including its local
    ID and locator. Original files may already have been cleaned up, so manual
    writes preserve that record instead of trying to reparse the original. Users
    may remove evidence or add/edit explicitly manual evidence with a different ID.
    """
    trusted = {
        item.id: item
        for item in (previous.evidence if previous is not None else [])
        if item.source_type != "manual"
    }
    for item in content.evidence:
        if item.id in trusted:
            if item != trusted[item.id]:
                raise invalid()
        elif item.source_type != "manual":
            raise invalid()


def validate_job(content: JobContent, raw_text: str) -> None:
    ids = [r.id for r in content.requirements]
    if not raw_text.strip() or len(set(ids)) != len(ids):
        raise invalid()
    for requirement in content.requirements:
        try:
            validate_condition(requirement)
        except ValueError:
            raise invalid() from None
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


def validate_score(
    score: ScoreResult,
    profile: ProfileContent,
    job: JobContent,
    verification: RequirementVerification | None = None,
) -> None:
    """Guard references/state fields before saving; M4 still owns computation."""
    requirements = {r.id: r for r in job.requirements if not r.ignored}
    ids = [a.requirement_id for a in score.assessments]
    evidence = {e.id for e in profile.evidence}
    if (
        len(set(ids)) != len(ids)
        or set(ids) != set(requirements)
        or (score.rule_version, score.matcher_version)
        not in {
            ("coverage-v1", "matcher-v1"),
            ("coverage-v2", "matcher-v2"),
            ("coverage-v3", "matcher-v3"),
        }
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
    if score.rule_version in {"coverage-v2", "coverage-v3"}:
        from app.scoring import assess_requirements, calculate_score
        from app.scoring.calculator import apply_requirement_verification

        expected = calculate_score(
            apply_requirement_verification(
                assess_requirements(profile, job, score.matcher_version), verification
            ),
            score.rule_version,
        )
        if score != expected:
            raise PlatformError(422, "MODEL_OUTPUT_INVALID", "评分与冻结材料的确定性计算不一致")
