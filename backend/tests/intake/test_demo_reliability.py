"""Candidate isolation, exact sources and neighboring valid expressions; no provider calls."""

from datetime import date

import pytest

from app.intake import IntakeError, validate_profile_content
from app.platform.validation import validate_profile
from app.scoring import assess_requirements, calculate_score
from app.structured_fields import defer_uncertain_attributes
from tests.intake.test_graduation_year import education, job
from tests.intake.test_pr76_context_review import arrival_job, arrival_profile


@pytest.mark.parametrize(
    "quote",
    [
        "目前尚未入职，可以立即到岗",
        "不能入职后值夜班，可以立即入职",
        "可立即到岗，但加班需等待四周",
        "每周三天到岗，可以立即到岗",
    ],
)
def test_current_state_and_work_conditions_do_not_reject_valid_arrival(quote):
    profile = arrival_profile(quote)
    result = defer_uncertain_attributes(profile)
    assert result == profile and not result.facts[0].unverified_attributes
    validate_profile_content(result, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(result, "2026-11")
    assert assess_requirements(result, arrival_job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "quote",
    [
        "可立即到岗，但需要四周通知期",
        "可立即到岗，但录用后四周才能开始工作",
        "可立即到岗，但目前不能入职",
        "目前尚未确定是否可以立即到岗",
    ],
)
def test_uncertain_arrival_is_preserved_and_other_requirements_still_score(quote):
    profile = arrival_profile(quote)
    original = profile.model_dump()
    result = defer_uncertain_attributes(profile)
    assert profile.model_dump() == original
    assert result.evidence == profile.evidence
    assert result.facts[0].unverified_attributes == profile.facts[0].attributes
    assert not result.facts[0].attributes
    assert defer_uncertain_attributes(result) == result  # Safe on repeated validation.
    validate_profile_content(result, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(result, "2026-11")
    assert assess_requirements(result, arrival_job(), "matcher-v3")[0].status == "unknown"

    from app.contracts import Evidence, Fact, Requirement

    result.evidence.append(
        Evidence(
            id="e2", source_type="manual", source_id="s2", quote="使用Python开发接口", locator=None
        )
    )
    result.facts.append(
        Fact(
            id="f2",
            kind="project",
            label="Python",
            value=None,
            polarity="positive",
            application="applied",
            start_month=None,
            end_month=None,
            completed=None,
            evidence_ids=["e2"],
        )
    )
    role = arrival_job()
    role.requirements.append(
        Requirement(
            id="r2",
            quote="Python",
            category="skill",
            importance="must",
            operator="has_skill",
            target="Python",
            subject=None,
            ignored=False,
            ignore_reason=None,
        )
    )
    score = calculate_score(assess_requirements(result, role, "matcher-v3"), "coverage-v3")
    assert score.score == 50  # Known Python counts; missing arrival stays in denominator.
    assert [a.status for a in score.assessments] == ["unknown", "met"]
    assert "待核对" in score.assessments[0].reason


def test_pending_graduation_cannot_be_resurrected_from_end_month():
    profile = education("预计2027年6月毕业", year="2028")
    profile.facts[0].end_month = "2027-06"
    result = defer_uncertain_attributes(profile)
    validate_profile(result, "2026-11")
    for criteria in (False, True):
        assessment = assess_requirements(result, job(criteria=criteria), "matcher-v3")[0]
        assert assessment.status == "unknown" and assessment.counted_in_score
    assert result.facts[0].end_month == "2027-06"  # Original candidate data is not rewritten.


def test_fabricated_quote_cannot_be_disguised_as_a_pending_attribute():
    profile = arrival_profile("可立即到岗，但需要四周通知期")
    profile.facts[0].attributes[0].quote = "原文没有这句话"
    with pytest.raises(ValueError, match="引用必须来自"):
        defer_uncertain_attributes(profile)
    profile.facts[0].unverified_attributes = profile.facts[0].attributes
    profile.facts[0].attributes = []
    with pytest.raises(ValueError, match="引用必须来自"):
        defer_uncertain_attributes(profile)


def test_exact_reference_to_fabricated_evidence_still_fails_source_validation():
    profile = defer_uncertain_attributes(arrival_profile("可立即到岗，但需要四周通知期"))
    with pytest.raises(IntakeError):
        validate_profile_content(profile, {"synthetic": "另一份实际原文"}, today=date(2026, 11, 8))


def test_candidate_cannot_also_be_used_as_confirmed_attribute():
    profile = arrival_profile("可立即到岗")
    profile.facts[0].unverified_attributes = list(profile.facts[0].attributes)
    with pytest.raises(ValueError, match="不能同时"):
        defer_uncertain_attributes(profile)
