"""Shared authorization-independent checks for a server-resolved diagnostic target."""

from app.contracts import (
    DiagnosisCreate,
    DiagnosisFocus,
    DiagnosisItem,
    Fact,
    Job,
    MessageCreate,
    Profile,
    ProfileContent,
    Requirement,
    RequirementVerification,
    ResourceVersion,
    VerifiedRequirement,
)
from app.contracts.ports import DiagnosisFocusContext
from app.platform.errors import missing
from app.platform.validation import invalid
from app.scoring.calculator import is_manual_only
from app.scoring.conditions import label, manual_evidence_conflict, manual_target_label


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
    result = body.model_dump(mode="json", exclude=exclude)
    if body.requirement_verification is not None and body.requirement_verification.fact_id is None:
        result["requirement_verification"].pop("fact_id")
    return result


def verification_fact(
    profile: ProfileContent, requirement: Requirement, evidence_id: str, fact_id: str | None
) -> Fact | None:
    candidates = [
        fact
        for fact in profile.facts
        if fact.polarity == "positive"
        and evidence_id in fact.evidence_ids
        and (fact_id is None or fact.id == fact_id)
    ]
    if len(candidates) == 1:
        return candidates[0]
    # Older requests can omit the fact only when the evidence identifies it uniquely.
    target = manual_target_label(requirement)
    exact = [fact for fact in candidates if label(fact.label) == target]
    return exact[0] if len(exact) == 1 else None


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
    evidence = {e.id: e for e in profile.content.evidence}
    previous_evidence = {e.id: e for e in previous_profile.content.evidence}
    retained: dict[str, tuple[VerifiedRequirement, Fact]] = {}
    for row in previous_verifications:
        requirement = eligible.get(row.requirement_id)
        if (
            requirement is None
            or row.evidence_id not in evidence
            or evidence[row.evidence_id] != previous_evidence.get(row.evidence_id)
        ):
            continue
        previous_fact = verification_fact(
            previous_profile.content, requirement, row.evidence_id, row.fact_id
        )
        if previous_fact is None:
            continue
        current_fact = verification_fact(
            profile.content, requirement, row.evidence_id, previous_fact.id
        )
        if current_fact is not None and current_fact.model_dump(
            exclude={"evidence_ids"}
        ) == previous_fact.model_dump(exclude={"evidence_ids"}):
            retained[row.requirement_id] = (
                row.model_copy(update={"fact_id": current_fact.id}),
                current_fact,
            )
    if verification.evidence_id is None and verification.fact_id is not None:
        raise invalid()
    if verification.evidence_id is not None:
        if (
            target.requirement.id not in eligible
            or target.assessment.unknown_reason not in {"manual_review", "conflicting_evidence"}
            or verification.evidence_id not in evidence
        ):
            raise invalid()
        fact = verification_fact(
            profile.content, target.requirement, verification.evidence_id, verification.fact_id
        )
        if fact is None:
            raise invalid()
        retained[target.requirement.id] = (
            VerifiedRequirement(
                requirement_id=target.requirement.id,
                evidence_id=verification.evidence_id,
                fact_id=fact.id,
            ),
            fact,
        )
    verified = []
    conflicts = {}
    for requirement_id, (row, fact) in retained.items():
        conflicting_ids = manual_evidence_conflict(eligible[requirement_id], profile.content, fact)
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
