"""Review 4d0d18b: arrival modifiers and follow-up events, synthetic only."""

from datetime import date

import pytest

from app.intake import IntakeError, validate_profile_content
from app.platform.errors import ProfileValidationError
from app.platform.validation import validate_profile
from app.scoring import assess_requirements
from app.scoring.errors import ScoringError
from tests.intake.test_pr76_context_review import arrival_job, arrival_profile


@pytest.mark.parametrize(
    "quote",
    [
        "目前尚未确定是否可以立即到岗",
        "目前不能保证可以立即到岗",
        "Not able to start immediately.",
        "可立即到岗，但目前不能到岗",
        "可立即到岗，但入职需等待四周",
        "可立即到岗，但到岗需要等两周",
    ],
)
@pytest.mark.parametrize("short", [False, True])
def test_arrival_uncertainty_blocks_confirmation_and_credit(quote, short):
    p = (
        arrival_profile(
            quote, "start immediately" if "start" in quote else "到岗" if "到岗" in quote else None
        )
        if short
        else arrival_profile(quote)
    )
    with pytest.raises(IntakeError):
        validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    with pytest.raises(ProfileValidationError):
        validate_profile(p, "2026-11")
    with pytest.raises(ScoringError):
        assess_requirements(p, arrival_job(), "matcher-v3")
    assert assess_requirements(p, arrival_job(), "matcher-v2")[0].status == "met"
    p.facts[0].attributes = []
    validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(p, "2026-11")
    assert assess_requirements(p, arrival_job(), "matcher-v3")[0].status == "unknown"


@pytest.mark.parametrize(
    "quote",
    [
        "不能加班但可立即到岗",
        "可立即到岗，但不能周末工作",
        "可立即到岗，但加班需等待四周",
        "目前可以保证立即到岗",
        "Able to start immediately.",
    ],
)
def test_other_subjects_and_affirmative_modifiers_remain_valid(quote):
    p = arrival_profile(quote)
    validate_profile_content(p, {"synthetic": quote}, today=date(2026, 11, 8))
    validate_profile(p, "2026-11")
    assert assess_requirements(p, arrival_job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize("tail", ["但目前不能到岗", "但入职需等待四周"])
@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_arrival_conflict_survives_linked_evidence_splitting(tail, reverse):
    p = arrival_profile("可立即到岗")
    p.evidence.append(p.evidence[0].model_copy(update={"id": "e2", "quote": tail}))
    with pytest.raises(ProfileValidationError):
        p.facts[0].evidence_ids.append("e2")
        if reverse:
            p.evidence.reverse()
        validate_profile(p, "2026-11")
    p.facts[0].evidence_ids = ["e1"]
    validate_profile(p, "2026-11")
