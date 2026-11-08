"""Review 4506138679: pending current arrangements must not disappear across facts."""

from datetime import date

import pytest

from app.intake import validate_profile_content
from app.platform.validation import validate_profile, validate_score
from app.scoring import assess_requirements, calculate_score
from app.structured_fields import defer_uncertain_attributes
from tests.intake.test_pr76_context_review import arrival_job, arrival_profile


def cross_fact_profile(origin="different_source", *, end_month=None):
    profile = arrival_profile("可以立即到岗")
    other = arrival_profile("可立即到岗，但需要四周通知期")
    fact, evidence = other.facts[0], other.evidence[0]
    fact.id, evidence.id = "f2", "e2"
    fact.evidence_ids = ["e2"]
    fact.end_month = end_month
    if end_month is not None:
        evidence.quote = f"历史到岗安排（已于{end_month}结束）：“{evidence.quote}”"
    if origin == "different_source":
        evidence.source_id = "synthetic-other"
    elif origin == "different_type":
        evidence.source_type = "message"
    profile.facts.append(fact)
    profile.evidence.append(evidence)
    return profile


def role_for(scope):
    role = arrival_job()
    requirement = role.requirements[0]
    if scope == "presence":
        requirement.operator = "has_evidence"
        requirement.quote = requirement.target = "提供到岗时间"
        requirement.condition = None
    else:
        requirement.condition.any_of[0].scope = scope
    return role


def check_saved(profile):
    sources = {}
    for item in profile.evidence:
        sources[item.source_id] = sources.get(item.source_id, "") + item.quote + "\n"
    validate_profile_content(profile, sources, today=date(2026, 11, 8))
    validate_profile(profile, "2026-11")


@pytest.mark.parametrize("origin", ["same_source", "different_source", "different_type"])
@pytest.mark.parametrize("scope", ["profile", "same_fact", "presence"])
@pytest.mark.parametrize("reverse", [False, True])
def test_current_pending_arrival_retains_both_sides_of_the_conflict(origin, scope, reverse):
    candidate = cross_fact_profile(origin)
    original = candidate.model_dump()
    profile = defer_uncertain_attributes(candidate)
    assert candidate.model_dump() == original
    assert not profile.facts[0].unverified_attributes
    assert profile.facts[1].unverified_attributes and not profile.facts[1].attributes
    if reverse:
        profile.facts.reverse()
        profile.evidence.reverse()
    check_saved(profile)
    frozen = profile.model_dump()
    job = role_for(scope)
    score = calculate_score(assess_requirements(profile, job, "matcher-v3"), "coverage-v3")
    assessment = score.assessments[0]
    assert assessment.status == "unknown"
    assert assessment.unknown_reason == "conflicting_evidence"
    assert assessment.evidence_ids == ["e1", "e2"]
    assert assessment.counted_in_score and score.scorable_weight_ratio == 1
    assert score.score == 0 and score.unknown_weight_ratio == 1
    validate_score(score, profile, job)
    assert profile.model_dump() == frozen


@pytest.mark.parametrize("scope", ["profile", "same_fact", "presence"])
@pytest.mark.parametrize("end_month,expected", [("2026-10", "met"), ("2026-11", "unknown")])
def test_explicitly_ended_arrangement_is_not_a_current_conflict(scope, end_month, expected):
    profile = defer_uncertain_attributes(cross_fact_profile(end_month=end_month))
    check_saved(profile)
    assessment = assess_requirements(profile, role_for(scope), "matcher-v3")[0]
    assert assessment.status == expected
    assert assessment.evidence_ids == (["e1"] if expected == "met" else ["e1", "e2"])


def test_source_age_and_unverified_month_do_not_silently_retire_a_candidate():
    profile = cross_fact_profile()
    profile.evidence[1].source_id = "document-uploaded-long-ago"
    profile.facts[1].attributes[0].value = "2025-01"
    # The text has no such date: its unverified value cannot establish history.
    result = defer_uncertain_attributes(profile)
    check_saved(result)
    assessment = assess_requirements(result, arrival_job(), "matcher-v3")[0]
    assert assessment.status == "unknown" and assessment.evidence_ids == ["e1", "e2"]


@pytest.mark.parametrize("scope", ["profile", "same_fact", "presence"])
@pytest.mark.parametrize(
    "quote",
    [
        "2026年10月上份实习结束，目前可立即到岗，但需要四周通知期",
        "可立即到岗，但需要四周通知期",  # No evidence for the supplied end_month.
        "历史安排截至2026-10：可立即到岗，但需要四周通知期",  # Which arrangement ended?
        "实习安排（已于2026-10结束）：“可立即到岗，但需要四周通知期”",
        "并非历史到岗安排（已于2026-10结束）：“可立即到岗，但需要四周通知期”",
        "如果历史到岗安排（已于2026-10结束）：“可立即到岗，但需要四周通知期”",
        "历史到岗安排（已于2026-11结束）：“可立即到岗，但需要四周通知期”",
        "历史到岗安排（已于2026-10结束）：“可立即到岗，但需要四周通知期”。目前仍需通知期",
    ],
)
def test_past_month_without_arrangement_evidence_cannot_discard_conflict(scope, quote):
    candidate = cross_fact_profile(end_month="2026-10")
    candidate.evidence[1].quote = quote
    profile = defer_uncertain_attributes(candidate)
    check_saved(profile)
    frozen = profile.model_dump()
    job = role_for(scope)
    score = calculate_score(assess_requirements(profile, job, "matcher-v3"), "coverage-v3")
    assessment = score.assessments[0]
    assert assessment.status == "unknown"
    assert assessment.unknown_reason == "conflicting_evidence"
    assert assessment.evidence_ids == ["e1", "e2"]
    assert assessment.counted_in_score and score.unknown_weight_ratio == 1
    validate_score(score, profile, job)
    assert profile.model_dump() == frozen


@pytest.mark.parametrize("same_source", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_historical_excerpt_cannot_hide_current_linked_evidence(same_source, reverse):
    candidate = cross_fact_profile(end_month="2026-10")
    extra = candidate.evidence[1].model_copy(
        update={
            "id": "e3",
            "source_id": candidate.evidence[1].source_id if same_source else "another-source",
            "quote": "目前可立即到岗，但需要四周通知期",
        }
    )
    candidate.evidence.append(extra)
    candidate.facts[1].evidence_ids.append("e3")
    if reverse:
        candidate.evidence.reverse()
        candidate.facts[1].evidence_ids.reverse()
    profile = defer_uncertain_attributes(candidate)
    check_saved(profile)
    assessment = assess_requirements(profile, arrival_job(), "matcher-v3")[0]
    assert assessment.status == "unknown"
    assert assessment.evidence_ids == ["e1", "e2", "e3"]


@pytest.mark.parametrize("month_text", ["2026-10", "2026年10月"])
@pytest.mark.parametrize("full_quote", [False, True])
def test_self_contained_historical_arrangement_has_bound_month_and_candidate(
    month_text, full_quote
):
    candidate = cross_fact_profile(end_month="2026-10")
    candidate.evidence[
        1
    ].quote = f"历史到岗安排（已于{month_text}结束）：“可立即到岗，但需要四周通知期”。"
    if full_quote:
        candidate.facts[1].attributes[0].quote = candidate.evidence[1].quote
    profile = defer_uncertain_attributes(candidate)
    check_saved(profile)
    assert assess_requirements(profile, arrival_job(), "matcher-v3")[0].status == "met"


def test_legacy_v2_does_not_reinterpret_pending_candidates():
    profile = defer_uncertain_attributes(cross_fact_profile())
    assert assess_requirements(profile, arrival_job(), "matcher-v2")[0].status == "met"


def test_pending_arrival_does_not_poison_an_independent_alternative():
    from app.contracts.models import ConditionGroup, Criterion, FactAttribute

    profile = cross_fact_profile()
    profile.evidence[0].quote += "，可以全职"
    profile.facts[0].attributes.append(
        FactAttribute(name="full_time", value="true", quote="可以全职")
    )
    profile = defer_uncertain_attributes(profile)
    check_saved(profile)
    job = arrival_job()
    job.requirements[0].quote = "立即到岗或可以全职"
    job.requirements[0].condition.any_of.append(
        ConditionGroup(
            scope="profile",
            all_of=[Criterion(field="full_time", comparison="eq", value="true", quote="可以全职")],
        )
    )
    assessment = assess_requirements(profile, job, "matcher-v3")[0]
    assert assessment.status == "met" and assessment.evidence_ids == ["e1"]
