import copy
from itertools import permutations

import pytest

from app.contracts import RequirementAssessment
from app.scoring import ScoringError, calculate_score


def assessment(id="r1", status="met", importance="preferred", category="skill"):
    return RequirementAssessment(
        requirement_id=id,
        status=status,
        importance=importance,
        category=category,
        weight=2 if importance == "must" else 1,
        coefficient={"met": 1, "partial": 0.5, "unmet": 0, "unknown": 0}[status],
        evidence_ids=[],
        reason="合成状态输入，仅用于验证公式。",
    )


def test_repository_hand_calculated_golden(example):
    expected = example("diagnosis-item.json")["score_result"]
    items = [RequirementAssessment.model_validate(x) for x in expected["assessments"]]
    actual = calculate_score(items)
    assert actual.score == 66.7
    assert actual.unknown_weight_ratio == 0.1667
    assert {x.category: x.score for x in actual.dimensions} == {"skill": 60, "education": 100}
    assert actual.rule_version == "coverage-v1"
    assert actual.matcher_version == "matcher-v1"


@pytest.mark.parametrize(
    "status,score,ratio", [("met", 100, 0), ("unknown", 0, 1), ("unmet", 0, 0), ("partial", 50, 0)]
)
def test_status_endpoints(status, score, ratio):
    result = calculate_score([assessment(status=status, importance="must")])
    assert (result.score, result.unknown_weight_ratio) == (score, ratio)


def test_total_is_not_average_of_categories():
    result = calculate_score(
        [assessment("r1", "met", "must"), assessment("r2", "unmet", category="education")]
    )
    assert result.score == 66.7
    assert result.score != sum(x.score for x in result.dimensions) / len(result.dimensions)
    assert {x.category for x in result.dimensions} == {"skill", "education"}


def test_round_half_up_for_score_and_unknown_ratio():
    # 100 / 80 = 1.25 -> 1.3; 1 / 32 = 0.03125 -> 0.0313.
    items = [assessment(f"r{i}", "unmet") for i in range(80)]
    items[0] = assessment("r0")
    assert calculate_score(items).score == 1.3
    items = [assessment(f"r{i}") for i in range(32)]
    items[0] = assessment("r0", "unknown")
    assert calculate_score(items).unknown_weight_ratio == 0.0313


def test_order_invariance_including_output_and_no_mutation(example):
    items = [
        RequirementAssessment.model_validate(x)
        for x in example("diagnosis-item.json")["score_result"]["assessments"]
    ]
    before = copy.deepcopy(items)
    expected = calculate_score(items).model_dump()
    for order in permutations(items):
        assert calculate_score(order).model_dump() == expected
    assert items == before


@pytest.mark.parametrize(
    "items,code",
    [
        ([], "NO_SCORABLE_REQUIREMENTS"),
        ([assessment(), assessment()], "INVALID_SCORING_INPUT"),
        ([assessment(id=" ")], "INVALID_SCORING_INPUT"),
    ],
)
def test_invalid_inputs_fail_explicitly(items, code):
    with pytest.raises(ScoringError) as error:
        calculate_score(items)
    assert error.value.code == code


@pytest.mark.parametrize("patch", [{"weight": 1}, {"coefficient": 0.5}])
def test_does_not_silently_repair_contradictory_states(patch):
    item = assessment(importance="must").model_copy(update=patch)
    with pytest.raises(ScoringError, match="权重或系数"):
        calculate_score([item])


def test_unknown_rule_version_cannot_silently_fall_back():
    with pytest.raises(ScoringError) as error:
        calculate_score([assessment()], "coverage-v2")
    assert error.value.code == "UNSUPPORTED_RULE_VERSION"
