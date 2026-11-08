"""Synthetic counterexamples from D's review of 7695e8d; no provider calls."""

from datetime import date

import pytest

from app.contracts import JobContent
from app.intake import IntakeError, validate_profile_content
from app.intake.validation import validate_job_content
from app.platform.errors import ProfileValidationError
from app.platform.validation import validate_profile
from app.scoring import assess_requirements
from app.scoring.errors import ScoringError
from tests.intake.test_pr76_context_review import arrival_job, arrival_profile
from tests.scoring.test_conditions import atom, fact, profile, requirement


@pytest.mark.parametrize(
    "quote",
    [
        "每周至少三天到岗，可立即到岗",
        "每周3-5天到岗，可立即入职",
        "每周 3 - 5天到岗，可立即入职",
        "每星期可至少三至五天到岗，可以立即到岗",
        "随时可以到岗",
        "立即可入职",
        "不能加班但可立即到岗",
        "Available immediately, but cannot work overtime.",
        "可立即到岗，但加班安排尚未确认",
    ],
)
def test_positive_arrival_expressions(quote):
    p = arrival_profile(quote)
    validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(p, "2026-11")
    assert assess_requirements(p, arrival_job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "quote",
    [
        "预计可立即到岗，但尚未确认",
        "目前不会立即到岗",
        "Available immediately, subject to four weeks notice.",
        "每周3-5天到岗，录用后三天到岗",
        "随时可以到岗，但还未确定",
        "现在不能立即入职",
        "Cannot start immediately.",
        "Available immediately, but not yet confirmed.",
    ],
)
def test_unconfirmed_or_delayed_arrival_stays_unknown(quote):
    p = arrival_profile(quote)
    with pytest.raises(IntakeError):
        validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    with pytest.raises(ProfileValidationError):
        validate_profile(p, "2026-11")
    with pytest.raises(ScoringError):
        assess_requirements(p, arrival_job(), "matcher-v3")
    assert assess_requirements(p, arrival_job(), "matcher-v2")[0].status == "met"
    p.facts[0].attributes = []
    validate_profile(p, "2026-11")
    assert assess_requirements(p, arrival_job(), "matcher-v3")[0].status == "unknown"


@pytest.mark.parametrize("degree", ["M.B.A.", "M.Sc.", "M. Sc."])
@pytest.mark.parametrize("has_cfa", [True, False])
def test_dotted_degree_is_manual_but_cfa_alternative_survives(degree, has_cfa):
    r = requirement(
        [atom("credential", degree, "complete")], [atom("credential", "CFA", "complete")]
    )
    j = JobContent(title="Synthetic", company_name=None, company_context="", requirements=[r])
    normalized = validate_job_content(j, r.quote).content
    p = profile(
        fact("credential", "CFA" if has_cfa else degree, [("credential_status", "complete")])
    )
    if not has_cfa:
        p.evidence[0].quote += f"；{degree}培训课程结业证书，尚未取得硕士学位"
    validate_profile(p, "2026-11")
    result = assess_requirements(p, normalized, "matcher-v3")[0]
    assert result.status == ("met" if has_cfa else "unknown")
    if not has_cfa:
        assert result.unknown_reason == "manual_review" and not result.counted_in_score
    assert j.requirements[0].condition.any_of[0].all_of[0].field == "credential"


@pytest.mark.parametrize(
    "boundary", ["same_source", "source_id", "source_type", "unlinked", "other_event"]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_arrival_qualifier_respects_fact_source_and_event_boundaries(boundary, reverse):
    p = arrival_profile("可立即到岗", "立即到岗")
    e = p.evidence[0].model_copy(update={"id": "e2", "quote": "但尚未确认"})
    if boundary == "source_id":
        e.source_id = "other"
    elif boundary == "source_type":
        e.source_type = "message"
    elif boundary == "other_event":
        e.quote = "但加班安排尚未确认"
    p.evidence.append(e)
    if boundary != "unlinked":
        p.facts[0].evidence_ids.append("e2")
    if reverse:
        p.evidence.reverse()
    if boundary == "same_source":
        with pytest.raises(ProfileValidationError):
            validate_profile(p, "2026-11")
    else:
        validate_profile(p, "2026-11")
        assert assess_requirements(p, arrival_job(), "matcher-v3")[0].status == "met"
