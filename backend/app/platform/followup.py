"""Shared authorization-independent checks for a server-resolved diagnostic target."""

from app.contracts import DiagnosisFocus, DiagnosisItem, Job, MessageCreate, ResourceVersion
from app.contracts.ports import DiagnosisFocusContext
from app.platform.errors import missing
from app.platform.validation import invalid


def message_request(body: MessageCreate) -> dict:
    # Preserve hashes of old requests whose DTO did not yet have these optional fields.
    result = body.model_dump(mode="json", exclude={"diagnosis_focus", "questions_only"})
    if body.diagnosis_focus is not None:
        result["diagnosis_focus"] = body.diagnosis_focus.model_dump(mode="json")
    if body.questions_only:
        result["questions_only"] = True
    return result


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
