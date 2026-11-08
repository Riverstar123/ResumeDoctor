"""Minimal regressions from the authorized synthetic DeepSeek material run."""

import pytest

from app.contracts.models import Fact
from app.structured_fields import validate_attributes


def availability(quote):
    return Fact(
        id="f1",
        kind="availability",
        label="到岗安排",
        value=None,
        polarity="positive",
        application="claimed",
        start_month=None,
        end_month=None,
        completed=None,
        evidence_ids=["e1"],
        attributes=[{"name": "availability_start", "value": "immediate", "quote": quote}],
    )


@pytest.mark.parametrize(
    "quote",
    [
        "可在录用后一个月内到岗",
        "可在录用后四周到岗",
        "目前离职，可两周内到岗",
        "Available with four weeks notice.",
        "Available after 4 weeks.",
    ],
)
def test_delayed_arrival_cannot_be_immediate(quote):
    validate_attributes(availability(quote), [quote], require_availability_context=False)
    with pytest.raises(ValueError, match="立即"):
        validate_attributes(availability(quote), [quote])


@pytest.mark.parametrize(
    "quote",
    [
        "可立即到岗",
        "每周可实习四天，可立即到岗",
        "Available immediately.",
        "Available immediately with four weeks of annual leave.",
    ],
)
def test_explicit_immediate_arrival_remains_valid(quote):
    validate_attributes(availability(quote), [quote])


@pytest.mark.parametrize("degree", ["MBA", "Master of Science"])
def test_academic_degrees_are_not_scored_as_professional_credentials(degree):
    from app.contracts import JobContent, Requirement
    from app.intake.validation import validate_job_content

    quote = f"Requires {degree}."
    requirement = Requirement(
        id="r1",
        quote=quote,
        category="education",
        importance="must",
        operator="criteria",
        target=degree,
        subject=None,
        ignored=False,
        ignore_reason=None,
        condition={
            "any_of": [
                {
                    "scope": "profile",
                    "all_of": [
                        {
                            "field": "credential",
                            "comparison": "complete",
                            "value": degree,
                            "quote": degree,
                        }
                    ],
                }
            ]
        },
    )
    job = JobContent(
        title="Synthetic analyst", company_name=None, company_context="", requirements=[requirement]
    )
    result = validate_job_content(job, quote).content.requirements[0]
    assert result.operator == "manual_review" and result.condition is None
    assert result.quote == quote
    assert job.requirements[0].condition is not None


def test_delayed_arrival_preserves_v2_replay_but_blocks_new_v3_credit():
    from app.contracts import JobContent, ProfileContent, Requirement
    from app.scoring import assess_requirements
    from app.scoring.errors import ScoringError

    quote = "Available with four weeks notice."
    profile = ProfileContent(
        overview="Synthetic",
        as_of_month="2026-11",
        facts=[availability(quote)],
        evidence=[
            dict(id="e1", source_type="manual", source_id="synthetic", quote=quote, locator=None)
        ],
    )
    requirement = Requirement(
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
    job = JobContent(
        title="Synthetic", company_name=None, company_context="", requirements=[requirement]
    )
    assert assess_requirements(profile, job, "matcher-v2")[0].status == "met"
    with pytest.raises(ScoringError):
        assess_requirements(profile, job, "matcher-v3")
