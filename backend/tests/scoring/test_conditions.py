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


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
@pytest.mark.parametrize(
    "field,name,denial_name",
    [
        ("skill", "SQL", "SQL"),
        ("skill", "Office", "Microsoft Office"),
        ("skill", "日语", "日语"),
        ("credential", "CPA", "CPA"),
        ("credential", "AWS Solutions Architect", "AWS Solutions Architect"),
    ],
)
def test_named_conditions_keep_related_positive_and_negative_evidence(
    scope, field, name, denial_name
):
    from datetime import date

    from app.intake import validate_profile_content
    from app.platform.validation import validate_profile, validate_score

    attributes = [("credential_status", "complete")] if field == "credential" else []
    p = profile(
        fact("credential" if field == "credential" else "project", name, attributes, applied=True),
        fact(
            "credential" if field == "credential" else "skill",
            denial_name,
            attributes,
            negative=True,
        ),
    )
    quotes = [
        f"在项目中应用 {name}。" if field == "skill" else f"已取得 {name} 完整资格。",
        f"我不会 {denial_name}。" if field == "skill" else f"我未通过 {denial_name} 考试。",
    ]
    for f, evidence, quote in zip(p.facts, p.evidence, quotes):
        evidence.quote = quote
        for attribute in f.attributes:
            attribute.quote = quote
    source = "\n".join(quotes)
    validate_profile_content(p, {"synthetic": source}, today=date(2026, 11, 5))
    validate_profile(p, p.as_of_month)
    before = p.model_dump()
    r = requirement([atom(field, name, "complete" if field == "credential" else "eq")], scope=scope)
    result = assess(p, r)[0]
    assert (result.status, result.unknown_reason) == ("unknown", "conflicting_evidence")
    assert result.evidence_ids == ["e0", "e1"]
    score = calculate_score([result], "coverage-v2")
    assert score.score == 0
    validate_score(
        score,
        p,
        JobContent(title="合成岗位", company_name=None, company_context="", requirements=[r]),
    )
    assert p.model_dump() == before


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
def test_credential_progress_conflict_is_not_resolved_by_selecting_one_record(scope):
    p = profile(
        fact("credential", "合成资格", [("credential_status", "complete")]),
        fact("credential", "合成资格", [("credential_status", "preparing")]),
    )
    result = assess(p, requirement([atom("credential", "合成资格", "complete")], scope=scope))[0]
    assert (result.status, result.unknown_reason, result.evidence_ids) == (
        "unknown",
        "conflicting_evidence",
        ["e0", "e1"],
    )


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
def test_named_conflicts_do_not_affect_an_independent_alternative(scope):
    p = profile(
        fact("project", "SQL", applied=True),
        fact("skill", "SQL", negative=True),
        fact("project", "Python", applied=True),
    )
    result = assess(p, requirement([atom("skill", "SQL")], [atom("skill", "Python")], scope=scope))[
        0
    ]
    assert result.status == "met" and result.evidence_ids == ["e2"]


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
def test_other_named_facts_do_not_conflict_with_the_requested_skill_or_credential(scope):
    p = profile(
        fact("project", "SQL", applied=True),
        fact("skill", "R", negative=True),
        fact("credential", "资格甲", [("credential_status", "complete")]),
        fact("credential", "资格乙", [("credential_status", "preparing")]),
    )
    for field, value, comparison in [("skill", "SQL", "eq"), ("credential", "资格甲", "complete")]:
        assert (
            assess(p, requirement([atom(field, value, comparison)], scope=scope))[0].status == "met"
        )


def test_same_fact_named_conditions_still_cannot_join_separate_records():
    p = profile(fact("project", "SQL", applied=True), fact("project", "Python", applied=True))
    result = assess(
        p, requirement([atom("skill", "SQL"), atom("skill", "Python")], scope="same_fact")
    )[0]
    assert result.status == "unknown" and calculate_score([result], "coverage-v2").score == 0


def test_year_disagreement_does_not_hide_a_threshold_both_records_meet():
    p = profile(fact("education", "合成学历", [("graduation_year", "2029")]))
    p.facts[0].end_month = "2028-06"
    a = assess(p, requirement([atom("graduation_year", "2028", "gte")]))[0]
    assert a.status == "met" and "仍需核对" in a.reason
    assert assess(p, requirement([atom("graduation_year", "2029", "gte")]))[0].status == "unknown"


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
@pytest.mark.parametrize(
    "field,first,second,target,comparison",
    [
        ("availability_days", "2", "5", "3", "gte"),
        ("availability_months", "2", "6", "3", "gte"),
        ("availability_start", "2026-11", "2026-12", "2026-11", "lte"),
        ("full_time", "true", "false", "true", "eq"),
    ],
)
def test_scoped_availability_keeps_global_conflicts(
    scope, field, first, second, target, comparison
):
    p = profile(
        fact("availability", "安排甲", [(field, first)]),
        fact("availability", "安排乙", [(field, second)]),
    )
    original = p.model_dump()
    a = assess(p, requirement([atom(field, target, comparison)], scope=scope))[0]
    assert (a.status, a.unknown_reason) == ("unknown", "conflicting_evidence")
    assert a.evidence_ids == ["e0", "e1"] and a.counted_in_score
    assert calculate_score([a], "coverage-v2").score == 0
    assert p.model_dump() == original


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
def test_availability_days_and_months_cannot_bypass_conflict(scope):
    p = profile(
        fact("availability", "安排甲", [("availability_days", "2"), ("availability_months", "3")]),
        fact("availability", "安排乙", [("availability_days", "5"), ("availability_months", "3")]),
    )
    r = requirement(
        [atom("availability_days", "3", "gte"), atom("availability_months", "3", "gte")],
        scope=scope,
    )
    from datetime import date

    from app.intake import validate_job_content, validate_profile_content
    from app.platform.validation import validate_job, validate_profile, validate_score

    source = "\n".join(e.quote for e in p.evidence)
    j = JobContent(title="合成岗位", company_name=None, company_context="", requirements=[r])
    validate_profile_content(p, {"synthetic": source}, today=date(2026, 11, 5))
    validate_profile(p, "2026-11")
    validate_job_content(j, r.quote)
    validate_job(j, r.quote)
    a = assess(p, r)[0]
    assert (a.status, a.unknown_reason, a.evidence_ids) == (
        "unknown",
        "conflicting_evidence",
        ["e0", "e1"],
    )
    validate_score(calculate_score([a], "coverage-v2"), p, j)


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
def test_scoped_availability_cannot_hide_explicit_denial(scope):
    p = profile(
        fact("availability", "安排甲", [("full_time", "true")]),
        fact("availability", "安排乙", [("full_time", "true")], negative=True),
    )
    a = assess(p, requirement([atom("full_time", "true")], scope=scope))[0]
    assert (a.status, a.unknown_reason, a.evidence_ids) == (
        "unknown",
        "conflicting_evidence",
        ["e0", "e1"],
    )


@pytest.mark.parametrize("comparison", ["eq", "gte", "lte"])
@pytest.mark.parametrize("target", ["2026-10", "2026-11", "2026-12"])
def test_immediate_uses_frozen_month_for_calendar_comparisons(comparison, target):
    p = profile(fact("availability", "安排", [("availability_start", "immediate")]))
    r = requirement([atom("availability_start", target, comparison)])
    for frozen in ("2026-11", "2025-01"):
        p.as_of_month = frozen
        expected = {"eq": frozen == target, "gte": frozen >= target, "lte": frozen <= target}[
            comparison
        ]
        a = assess(p, r)[0]
        assert a.status == ("met" if expected else "unmet")
        assert a.evidence_ids == ["e0"] and a.unknown_reason is None
        assert p.facts[0].attributes[0].value == "immediate"


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
def test_immediate_and_same_frozen_month_are_not_conflicting(scope):
    p = profile(
        fact("availability", "安排甲", [("availability_start", "immediate")]),
        fact("availability", "安排乙", [("availability_start", "2026-11")]),
    )
    a = assess(p, requirement([atom("availability_start", "2026-12", "lte")], scope=scope))[0]
    assert a.status == "met" and a.unknown_reason is None


@pytest.mark.parametrize(
    "value,expected",
    [("2026-10", "unknown"), ("2026-11", "unknown"), ("2026-12", "unmet"), ("immediate", "met")],
)
def test_month_precision_does_not_invent_immediate_commitment(value, expected):
    p = profile(fact("availability", "安排", [("availability_start", value)]))
    a = assess(p, requirement([atom("availability_start", "immediate")]))[0]
    assert a.status == expected
    if expected == "unknown":
        assert a.unknown_reason == "missing_evidence"


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
@pytest.mark.parametrize("completed,state", [(True, "enrolled"), (False, "completed")])
def test_legacy_education_state_conflict_stays_unknown(scope, completed, state):
    p = profile(fact("education", "合成学历", [("enrollment", state)]))
    p.facts[0].completed = completed
    p.facts[0].end_month = "2025-06"
    original = p.model_dump()
    a = assess(p, requirement([atom("enrollment", state)], scope=scope))[0]
    assert (a.status, a.unknown_reason, a.evidence_ids) == (
        "unknown",
        "conflicting_evidence",
        ["e0"],
    )
    assert p.model_dump() == original


def test_legacy_education_conflict_cannot_prove_completed_degree():
    p = profile(fact("education", "合成学历", [("enrollment", "enrolled")]))
    p.facts[0].completed = True
    r = Requirement(
        id="r1",
        quote="已取得硕士学历",
        category="education",
        importance="must",
        operator="degree_at_least",
        target="master",
        ignored=False,
        ignore_reason=None,
        subject=None,
    )
    a = assess(p, r)[0]
    assert (a.status, a.unknown_reason) == ("unknown", "conflicting_evidence")
    assert a.evidence_ids == ["e0"]
    # An independent, consistent qualification can still meet the requirement.
    good = p.facts[0].model_copy(deep=True, update={"id": "f1", "attributes": []})
    p.facts.append(good)
    assert assess(p, r)[0].status == "met"


def test_same_fact_availability_still_cannot_join_separate_commitments():
    p = profile(
        fact("availability", "安排甲", [("availability_days", "5")]),
        fact("availability", "安排乙", [("availability_months", "3")]),
    )
    atoms = [atom("availability_days", "3", "gte"), atom("availability_months", "3", "gte")]
    assert assess(p, requirement(atoms, scope="profile"))[0].status == "met"
    a = assess(p, requirement(atoms, scope="same_fact"))[0]
    assert (a.status, a.unknown_reason) == ("unknown", "missing_evidence")


@pytest.mark.parametrize("scope", ["profile", "same_fact"])
@pytest.mark.parametrize(
    "field,positive,negative,target,comparison",
    [
        ("availability_days", "2", "2", "3", "gte"),
        ("availability_start", "immediate", "2026-11", "immediate", "eq"),
    ],
)
def test_current_commitment_cannot_ignore_a_denied_equivalent_value(
    scope, field, positive, negative, target, comparison
):
    p = profile(
        fact("availability", "安排甲", [(field, positive)]),
        fact("availability", "安排乙", [(field, negative)], negative=True),
    )
    a = assess(p, requirement([atom(field, target, comparison)], scope=scope))[0]
    assert (a.status, a.unknown_reason, a.evidence_ids) == (
        "unknown",
        "conflicting_evidence",
        ["e0", "e1"],
    )
