"""Cross-domain semantic regression: all inputs are explicit synthetic facts."""

from copy import deepcopy
from itertools import permutations

import pytest

from app.contracts import JobContent, ProfileContent, Requirement
from app.scoring import assess_requirements, calculate_score
from app.scoring.errors import ScoringError
from app.structured_fields import validate_condition


def profile(*facts):
    items, evidence = [], []
    for i, (kind, name, attributes, polarity, application) in enumerate(facts):
        quote = "合成原文：" + name + "；" + "；".join(f"{k}={v}" for k, v in attributes)
        eid = f"e{i}"
        evidence.append(
            dict(id=eid, source_type="manual", source_id="synthetic", quote=quote, locator=None)
        )
        items.append(
            dict(
                id=f"f{i}",
                kind=kind,
                label=name,
                value="master" if kind == "education" else None,
                polarity=polarity,
                application=application,
                start_month=None,
                end_month=None,
                completed=None,
                evidence_ids=[eid],
                attributes=[dict(name=k, value=v, quote=quote) for k, v in attributes],
            )
        )
    return ProfileContent(
        overview="合成回归", as_of_month="2026-11", facts=items, evidence=evidence
    )


def fact(kind, name, attrs=(), *, negative=False, applied=False):
    return (
        kind,
        name,
        attrs,
        "negative" if negative else "positive",
        "applied" if applied else "claimed",
    )


def atom(field, value, comparison="eq"):
    return dict(field=field, value=value, comparison=comparison, quote="合成岗位条件")


def requirement(*groups, scope="profile", id="r1"):
    return Requirement(
        id=id,
        quote="合成岗位条件",
        category="other",
        importance="must",
        operator="criteria",
        target="条件组合",
        subject=None,
        ignored=False,
        ignore_reason=None,
        condition={"any_of": [{"scope": scope, "all_of": group} for group in groups]},
    )


def assess(p, *reqs):
    j = JobContent(title="合成岗位", company_name=None, company_context="", requirements=list(reqs))
    return assess_requirements(p, j, "matcher-v2")


@pytest.mark.parametrize("first,second", [("Python", "R"), ("Figma", "Sketch"), ("日语", "法语")])
def test_alternatives_are_one_requirement_and_one_weight(first, second):
    p = profile(fact("experience", first, applied=True))
    a = assess(p, requirement([atom("skill", first)], [atom("skill", second)]))
    assert len(a) == 1 and a[0].status == "met"
    assert calculate_score(a, "coverage-v2").score == 100
    assert (
        assess(p, requirement([atom("skill", first), atom("skill", second)]))[0].status == "unknown"
    )


@pytest.mark.parametrize("name", ["CFA", "CPA", "AWS Solutions Architect", "教师资格"])
def test_credential_progress_is_generic_not_name_specific(name):
    p = profile(
        fact("credential", name, [("credential_status", "partial"), ("credential_level", "阶段一")])
    )
    assert assess(p, requirement([atom("credential", name, "any_pass")]))[0].status == "met"
    assert assess(p, requirement([atom("credential", name, "complete")]))[0].status == "unmet"
    prep = profile(fact("credential", name, [("credential_status", "preparing")]))
    assert assess(prep, requirement([atom("credential", name, "any_pass")]))[0].status == "unmet"


def test_credential_or_does_not_penalize_missing_alternative():
    p = profile(fact("credential", "考试B", [("credential_status", "partial")]))
    a = assess(
        p,
        requirement(
            [atom("credential", "考试A", "any_pass")], [atom("credential", "考试B", "any_pass")]
        ),
    )[0]
    assert a.status == "met" and a.evidence_ids == ["e0"]


@pytest.mark.parametrize(
    "suite,component",
    [
        ("Office", "Excel"),
        ("Microsoft Office", "PowerPoint"),
        ("Adobe Creative Cloud", "Photoshop"),
    ],
)
def test_suite_component_is_partial_never_full(suite, component):
    p = profile(fact("experience", component, applied=True))
    assert assess(p, requirement([atom("skill", suite)]))[0].status == "partial"
    assert assess(p, requirement([atom("skill", component)]))[0].status == "met"


def test_similar_and_contained_labels_do_not_prove_skills():
    p = profile(
        fact("experience", "JavaScript", applied=True), fact("experience", "C++", applied=True)
    )
    for target in ["Java", "C", "机器学习"]:
        assert assess(p, requirement([atom("skill", target)]))[0].status == "unknown"


def test_different_degrees_cannot_be_joined_to_meet_same_fact_condition():
    p = profile(
        fact("education", "本科", [("major", "数学"), ("enrollment", "completed")]),
        fact("education", "硕士", [("major", "历史"), ("enrollment", "enrolled")]),
    )
    r = requirement([atom("major", "数学"), atom("enrollment", "enrolled")], scope="same_fact")
    assert assess(p, r)[0].status != "met"
    p.facts[1].attributes[0].value = "数学"
    assert assess(p, r)[0].status == "met"


def test_explicit_graduation_year_has_no_invented_month():
    p = profile(fact("education", "硕士", [("graduation_year", "2028")]))
    a = assess(p, requirement([atom("graduation_year", "2027", "gte")]))[0]
    assert a.status == "met" and p.facts[0].end_month is None


def test_contradictory_years_remain_unknown_even_if_both_pass_threshold():
    p = profile(
        fact("education", "硕士", [("graduation_year", "2028"), ("graduation_year", "2029")])
    )
    a = assess(p, requirement([atom("graduation_year", "2027", "gte")]))[0]
    assert a.status == "unknown" and a.unknown_reason == "conflicting_evidence"


def test_past_experience_never_proves_future_availability():
    p = profile(fact("experience", "软件开发", [("experience_type", "internship")], applied=True))
    p.facts[0].start_month = "2024-01"
    p.facts[0].end_month = "2025-01"
    for field, target in [("availability_days", "3"), ("availability_months", "6")]:
        assert assess(p, requirement([atom(field, target, "gte")]))[0].status == "unknown"
    available = profile(
        fact("availability", "工作安排", [("availability_days", "4"), ("availability_months", "6")])
    )
    assert (
        assess(
            available,
            requirement(
                [atom("availability_days", "3", "gte"), atom("availability_months", "6", "gte")]
            ),
        )[0].status
        == "met"
    )
    assert (
        assess(available, requirement([atom("availability_days", "5", "gte")]))[0].status == "unmet"
    )


def test_unknown_manual_has_existing_evidence_and_separate_denominator():
    p = profile(
        fact("education", "硕士", [("institution", "合成大学")]),
        fact("experience", "R", applied=True),
    )
    manual = Requirement(
        id="r2",
        quote="知名院校",
        category="education",
        importance="must",
        operator="manual_review",
        target="知名院校",
        subject=None,
        ignored=False,
        ignore_reason=None,
    )
    a = assess(p, requirement([atom("skill", "R")]), manual)
    review = a[1]
    assert review.unknown_reason == "manual_review" and review.evidence_ids == ["e0"]
    assert not review.counted_in_score
    s = calculate_score(a, "coverage-v2")
    assert s.score == 100 and s.scorable_weight_ratio == 0.5 and s.unknown_weight_ratio == 0.5
    with pytest.raises(ScoringError):
        calculate_score(a, "coverage-v1")
    missing = assess(p, requirement([atom("availability_months", "6", "gte")]))[0]
    assert missing.counted_in_score
    missing.counted_in_score = False
    with pytest.raises(ScoringError):
        calculate_score([missing], "coverage-v2")


def test_no_scorable_items_is_explicitly_distinguished_from_zero_match():
    r = Requirement(
        id="r",
        quote="认真",
        category="other",
        importance="must",
        operator="manual_review",
        target="认真",
        subject=None,
        ignored=False,
        ignore_reason=None,
    )
    result = calculate_score(assess(profile(), r), "coverage-v2")
    assert result.scorable_weight_ratio == 0 and result.unknown_weight_ratio == 1


def test_deterministic_and_non_mutating_under_reordering():
    p = profile(fact("experience", "R", applied=True))
    requirements = [
        requirement([atom("skill", "R")], id="a"),
        requirement([atom("skill", "SQL")], id="b"),
    ]
    original = deepcopy(p)
    scores = [
        calculate_score(assess(p, *order), "coverage-v2").model_dump()
        for order in permutations(requirements)
    ]
    assert scores[0] == scores[1] and p == original


def test_negative_and_positive_skill_evidence_are_not_resolved_optimistically():
    p = profile(fact("experience", "SQL", applied=True), fact("skill", "SQL", negative=True))
    a = assess(p, requirement([atom("skill", "SQL")]))[0]
    assert a.status == "unknown" and a.unknown_reason == "conflicting_evidence"


@pytest.mark.parametrize(
    "field,value,comparison",
    [
        ("availability_days", "8", "gte"),
        ("availability_months", "很多", "gte"),
        ("enrollment", "yes", "eq"),
        ("skill", "SQL", "gte"),
    ],
)
def test_invalid_condition_values_are_rejected(field, value, comparison):
    with pytest.raises(ValueError):
        validate_condition(requirement([atom(field, value, comparison)]))


def test_attribute_evidence_cannot_come_from_another_fact():
    p = profile(
        fact("education", "数学", [("major", "数学")]),
        fact("education", "医学", [("major", "医学")]),
    )
    p.facts[0].attributes[0].quote = p.evidence[1].quote
    with pytest.raises(ScoringError):
        assess(p, requirement([atom("major", "数学")]))


def test_unrelated_facts_cannot_mask_decisive_same_fact_failure():
    p = profile(fact("education", "degree", [("graduation_year", "2024")]), fact("skill", "Python"))
    a = assess(p, requirement([atom("graduation_year", "2027", "gte")], scope="same_fact"))[0]
    assert a.status == "unmet"


def test_incompatible_same_fact_fields_are_rejected():
    with pytest.raises(ValueError, match="共同事实类别"):
        validate_condition(
            requirement(
                [atom("major", "统计"), atom("credential", "证书", "complete")], scope="same_fact"
            )
        )


def test_current_availability_conflict_cannot_pick_optimistic_value():
    p = profile(
        fact("availability", "安排甲", [("availability_days", "2")]),
        fact("availability", "安排乙", [("availability_days", "5")]),
    )
    a = assess(p, requirement([atom("availability_days", "3", "gte")]))[0]
    assert a.status == "unknown" and a.unknown_reason == "conflicting_evidence"


def test_condition_dedup_ignores_title_and_branch_order():
    p = profile(fact("experience", "Python", applied=True))
    r = requirement([atom("skill", "Python")], [atom("skill", "R")])
    duplicate = r.model_copy(deep=True)
    duplicate.id = "r2"
    duplicate.target = "另一说明标题"
    duplicate.condition.any_of.reverse()
    assert len(assess(p, r, duplicate)) == 1


def test_v2_persistence_rejects_forged_denominator_or_score():
    from app.platform.errors import PlatformError
    from app.platform.validation import validate_score

    p = profile(fact("experience", "Python", applied=True))
    r = requirement([atom("skill", "Python")])
    j = JobContent(title="合成", company_name=None, company_context="", requirements=[r])
    score = calculate_score(assess(p, r), "coverage-v2")
    validate_score(score, p, j)
    for update in ({"score": 0}, {"scorable_weight_ratio": 0}):
        with pytest.raises(PlatformError):
            validate_score(score.model_copy(update=update), p, j)


def test_graduation_label_conflicting_with_end_date_requires_confirmation():
    p = profile(
        fact("education", "合成学历", [("graduation_year", "2029"), ("enrollment", "enrolled")])
    )
    p.facts[0].end_month = "2028-06"
    for c in [atom("graduation_year", "2029", "gte"), atom("enrollment", "enrolled")]:
        a = assess(p, requirement([c]))[0]
        assert a.status == "unknown" and a.unknown_reason == "conflicting_evidence"


def test_vague_season_cannot_ground_invented_start_month():
    from app.structured_fields import validate_attributes

    p = profile(fact("availability", "安排", [("availability_start", "2028-07")]))
    p.facts[0].attributes[0].quote = "2028年暑期"
    with pytest.raises(ValueError, match="原文明示年月"):
        validate_attributes(p.facts[0], ["2028年暑期"])
    p.facts[0].attributes[0].quote = "2028年7月"
    validate_attributes(p.facts[0], ["2028年7月"])


@pytest.mark.parametrize("name,level", [("考试A", "阶段一"), ("CFA", "Level I"), ("资格B", "初级")])
def test_level_qualified_credential_can_meet_any_pass_but_not_complete_parent(name, level):
    p = profile(
        fact(
            "credential",
            name + " " + level,
            [("credential_level", level), ("credential_status", "complete")],
        )
    )
    assert assess(p, requirement([atom("credential", name, "any_pass")]))[0].status == "met"
    assert assess(p, requirement([atom("credential", name, "complete")]))[0].status == "unmet"
    assert (
        assess(p, requirement([atom("credential", name + " " + level, "complete")]))[0].status
        == "met"
    )


def test_year_disagreement_does_not_hide_a_threshold_both_records_meet():
    p = profile(fact("education", "合成学历", [("graduation_year", "2029")]))
    p.facts[0].end_month = "2028-06"
    a = assess(p, requirement([atom("graduation_year", "2028", "gte")]))[0]
    assert a.status == "met" and "仍需核对" in a.reason
    assert assess(p, requirement([atom("graduation_year", "2029", "gte")]))[0].status == "unknown"
