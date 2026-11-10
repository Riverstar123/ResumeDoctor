"""Shared authorization-independent checks for a server-resolved diagnostic target."""

from app.contracts import (
    DiagnosisCreate,
    DiagnosisFocus,
    DiagnosisItem,
    Job,
    MessageCreate,
    Profile,
    RequirementVerification,
    ResourceVersion,
    VerifiedRequirement,
)
from app.contracts.ports import DiagnosisFocusContext
from app.platform.errors import missing
from app.platform.validation import invalid
from app.scoring.calculator import is_manual_only
from app.scoring.conditions import manual_evidence_conflict


def message_request(body: MessageCreate) -> dict:
    # Preserve hashes of old requests whose DTO did not yet have these optional fields.
    result = body.model_dump(mode="json", exclude={"diagnosis_focus", "questions_only"})
    if body.diagnosis_focus is not None:
        result["diagnosis_focus"] = body.diagnosis_focus.model_dump(mode="json")
    if body.questions_only:
        result["questions_only"] = True
    return result


def diagnosis_request(body: DiagnosisCreate) -> dict:
    exclude = {"requirement_verification"} if body.requirement_verification is None else set()
    return body.model_dump(mode="json", exclude=exclude)


def resolve_verifications(
    verification: RequirementVerification,
    target: DiagnosisFocusContext,
    profile: Profile,
    jobs: list[Job],
    previous_profile: Profile,
    previous_verifications: list[VerifiedRequirement],
) -> tuple[list[VerifiedRequirement], dict[str, list[str]]]:
    if (
        len(jobs) != 1
        or (jobs[0].id, jobs[0].version) != (target.job.id, target.job.version)
        or profile.version <= target.profile.version
    ):
        raise invalid()
    eligible = {
        r.id: r for r in jobs[0].content.requirements if not r.ignored and is_manual_only(r)
    }
    positive_evidence_ids = {
        evidence_id
        for fact in profile.content.facts
        if fact.polarity == "positive"
        for evidence_id in fact.evidence_ids
    }
    evidence = {e.id: e for e in profile.content.evidence if e.id in positive_evidence_ids}
    previous_evidence = {e.id: e for e in previous_profile.content.evidence}
    retained = {
        row.requirement_id: row
        for row in previous_verifications
        if row.requirement_id in eligible
        and row.evidence_id in evidence
        and evidence[row.evidence_id] == previous_evidence.get(row.evidence_id)
    }
    if verification.evidence_id is not None:
        if (
            target.requirement.id not in eligible
            or target.assessment.unknown_reason not in {"manual_review", "conflicting_evidence"}
            or verification.evidence_id not in evidence
        ):
            raise invalid()
        retained[target.requirement.id] = VerifiedRequirement(
            requirement_id=target.requirement.id, evidence_id=verification.evidence_id
        )
    verified = []
    conflicts = {}
    for requirement_id, row in retained.items():
        conflicting_ids = manual_evidence_conflict(
            eligible[requirement_id], profile.content, row.evidence_id
        )
        if conflicting_ids:
            conflicts[requirement_id] = list(conflicting_ids)
        else:
            verified.append(row)
    return verified, conflicts


def focus_context(
    focus: DiagnosisFocus,
    profile_id: str,
    diagnosis_profile: ResourceVersion,
    item: DiagnosisItem,
    job: Job,
) -> DiagnosisFocusContext:
    if (
        diagnosis_profile.id.lower() != profile_id.lower()
        or item.id.lower() != focus.item_id.lower()
    ):
        raise missing()
    if item.job.id != job.id or item.job.version != job.version:
        raise missing()
    if item.status not in {"succeeded", "score_only"} or item.score_result is None:
        raise invalid()
    requirement = next(
        (r for r in job.content.requirements if r.id == focus.requirement_id and not r.ignored),
        None,
    )
    assessment = next(
        (a for a in item.score_result.assessments if a.requirement_id == focus.requirement_id), None
    )
    if requirement is None or assessment is None or assessment.status == "met":
        raise invalid()
    gap = (
        next((g for g in item.report.gaps if g.requirement_id == focus.requirement_id), None)
        if item.report
        else None
    )
    return DiagnosisFocusContext(
        diagnosis_id=focus.diagnosis_id.lower(),
        item_id=item.id,
        profile=diagnosis_profile.model_copy(deep=True),
        job=item.job.model_copy(deep=True),
        job_title=job.content.title,
        requirement=requirement.model_copy(deep=True),
        assessment=assessment.model_copy(deep=True),
        gap=gap.model_copy(deep=True) if gap else None,
    )
