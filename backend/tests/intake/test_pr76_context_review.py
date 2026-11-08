"""D's five 1573b48 counterexamples; synthetic data, no model calls."""

from datetime import date

import pytest

from app.contracts import JobContent, ProfileContent, Requirement
from app.intake import IntakeError, validate_profile_content
from app.intake.validation import validate_job_content
from app.platform.errors import ProfileValidationError
from app.platform.validation import validate_profile
from app.scoring import assess_requirements, calculate_score
from app.scoring.errors import ScoringError
from tests.intake.test_graduation_year import education, job, split_graduation_adjustment
from tests.intake.test_real_material_regressions import availability
from tests.scoring.test_conditions import fact, profile


def arrival_profile(quote, short=None):
    f = availability(quote)
    if short:
        f.attributes[0].quote = short
    return ProfileContent(
        overview="Synthetic",
        as_of_month="2026-11",
        facts=[f],
        evidence=[
            dict(id="e1", source_type="manual", source_id="synthetic", quote=quote, locator=None)
        ],
    )


def arrival_job():
    return JobContent(
        title="Synthetic",
        company_name=None,
        company_context="",
        requirements=[
            Requirement(
                id="r1",
                quote="立即到岗",
                category="other",
                importance="must",
                operator="criteria",
                target="到岗",
                subject=None,
                ignored=False,
                ignore_reason=None,
                condition={
                    "any_of": [
                        {
                            "scope": "profile",
                            "all_of": [
                                {
                                    "field": "availability_start",
                                    "comparison": "eq",
                                    "value": "immediate",
                                    "quote": "立即到岗",
                                }
                            ],
                        }
                    ]
                },
            )
        ],
    )


@pytest.mark.parametrize(
    "quote",
    [
        "每周三天到岗，可以立即到岗",
        "每星期三天到岗、立即开始",
        "每周可四天到岗，可立即到岗",
    ],
)
def test_weekly_attendance_does_not_become_start_delay(quote):
    p = arrival_profile(quote)
    validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(p, "2026-11")
    assert assess_requirements(p, arrival_job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "quote",
    [
        "可在录用后一个月内到岗",
        "录用后三天到岗",
        "到岗安排待确认",
        "不能立即到岗",
    ],
)
def test_short_arrival_quote_cannot_hide_delay_or_lack_of_commitment(quote):
    p = arrival_profile(quote, "到岗")
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


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
@pytest.mark.parametrize("has_cfa", [True, False])
def test_degree_alternative_preserves_the_automatic_cfa_branch(scope, has_cfa):
    quote = "须持有 CFA 或 MBA"
    r = Requirement(
        id="r1",
        quote=quote,
        category="education",
        importance="must",
        operator="criteria",
        target="CFA或MBA",
        subject=None,
        ignored=False,
        ignore_reason=None,
        condition={
            "any_of": [
                {
                    "scope": scope,
                    "all_of": [
                        {"field": "credential", "comparison": "complete", "value": v, "quote": v}
                    ],
                }
                for v in ["CFA", "MBA"]
            ]
        },
    )
    j = JobContent(title="Synthetic", company_name=None, company_context="", requirements=[r])
    normalized = validate_job_content(j, quote).content
    p = (
        profile(fact("credential", "CFA", [("credential_status", "complete")]))
        if has_cfa
        else education("2027年硕士毕业")
    )
    result = assess_requirements(p, normalized, "matcher-v3")
    if has_cfa:
        assert result[0].status == "met" and calculate_score(result, "coverage-v3").score == 100
    else:
        assert result[0].status == "unknown" and result[0].unknown_reason == "manual_review"
        assert not result[0].counted_in_score
    assert j.requirements[0].condition.any_of[1].all_of[0].field == "credential"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("qualifier", ["但实际已延期", "但尚未确认"])
def test_split_uncertainty_without_a_new_year_blocks_graduation(reverse, qualifier):
    p = split_graduation_adjustment(reverse=reverse)
    next(e for e in p.evidence if e.id == "e2").quote = qualifier
    with pytest.raises(IntakeError):
        validate_profile_content(
            p, {"synthetic": "预计2027年6月硕士毕业，" + qualifier}, today=date(2026, 11, 8)
        )
    with pytest.raises(ProfileValidationError):
        validate_profile(p, "2026-11")
    with pytest.raises(ScoringError):
        assess_requirements(p, job(criteria=True), "matcher-v3")
    p.facts[0].attributes = []
    p.facts[0].end_month = "2027-06"
    validate_profile(p, "2026-11")
    assert assess_requirements(p, job(), "matcher-v3")[0].status == "unknown"


@pytest.mark.parametrize(
    "quote",
    [
        "本科2024年毕业并硕士预计2027年6月毕业",
        "本科2024年毕业，硕士预计2027年6月毕业",
    ],
)
def test_prefix_degree_binds_each_graduation_event(quote):
    p = education(quote, attribute_quote="2027年6月毕业")
    validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(p, "2026-11")
    assert assess_requirements(p, job(criteria=True), "matcher-v3")[0].status == "met"
    p.facts[0].attributes = []
    p.facts[0].end_month = "2027-06"
    assert assess_requirements(p, job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "boundary", ["source_id", "source_type", "unlinked_fact", "internship", "other_degree"]
)
def test_graduation_uncertainty_stays_with_its_event(boundary):
    p = split_graduation_adjustment()
    p.evidence[1].quote = "但实际已延期"
    if boundary == "source_id":
        p.evidence[1].source_id = "other"
    elif boundary == "source_type":
        p.evidence[1].source_type = "message"
    elif boundary == "unlinked_fact":
        p.facts[0].evidence_ids = ["e1"]
    else:
        p.evidence.insert(
            1,
            p.evidence[0].model_copy(
                update={
                    "id": "e3",
                    "quote": "实习开始日期待确认" if boundary == "internship" else "本科2024年毕业",
                }
            ),
        )
        p.facts[0].evidence_ids.append("e3")
    validate_profile(p, "2026-11")
    assert assess_requirements(p, job(criteria=True), "matcher-v3")[0].status == "met"


def test_two_prefix_dates_for_the_same_degree_still_conflict():
    p = education("硕士2026年毕业并硕士预计2027年6月毕业", attribute_quote="2027年6月毕业")
    with pytest.raises(ProfileValidationError):
        validate_profile(p, "2026-11")


def test_short_arrival_quote_uses_linked_context_only():
    p = arrival_profile("每周三天到岗，可以立即到岗", "立即到岗")
    p.evidence.append(p.evidence[0].model_copy(update={"id": "e2", "quote": "录用后三天到岗"}))
    validate_profile(p, "2026-11")  # Unlinked evidence is not this fact's context.
    p.facts[0].evidence_ids.append("e2")
    with pytest.raises(ProfileValidationError):
        validate_profile(p, "2026-11")


def test_manual_alternative_keeps_conjunction_and_v2_replay():
    from tests.scoring.test_conditions import atom, requirement

    # A disproved conjunction cannot hide the missing automatic alternative.
    r = requirement(
        [atom("credential", "CFA", "complete")], [atom("manual", "MBA"), atom("skill", "SQL")]
    )
    j = JobContent(title="Synthetic", company_name=None, company_context="", requirements=[r])
    p = profile(fact("skill", "SQL", negative=True))
    assert assess_requirements(p, j, "matcher-v3")[0].unknown_reason == "missing_evidence"
    p = profile(fact("skill", "Python"))
    assert assess_requirements(p, j, "matcher-v3")[0].unknown_reason == "manual_review"
    assert assess_requirements(p, j, "matcher-v2")[0].unknown_reason == "missing_evidence"


def test_same_fact_degree_conjunction_remains_bounded_and_manual():
    from tests.scoring.test_conditions import atom, requirement

    r = requirement(
        [atom("credential", "CFA", "complete")],
        [atom("credential", "MBA", "complete"), atom("credential", "X" * 200, "complete")],
        scope="same_fact",
    )
    j = JobContent(title="Synthetic", company_name=None, company_context="", requirements=[r])
    normalized = validate_job_content(j, r.quote).content
    JobContent.model_validate(normalized.model_dump())
    assert normalized.requirements[0].condition.any_of[1].scope == "profile"
    assert normalized.requirements[0].condition.any_of[1].all_of[0].field == "manual"
    p = profile(fact("credential", "CFA", [("credential_status", "complete")]))
    assert assess_requirements(p, normalized, "matcher-v3")[0].status == "met"
