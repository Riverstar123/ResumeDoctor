"""C's PR #76 counterexample: a course end must not become a graduation year."""

import asyncio
from datetime import date

import pytest

from app.contracts import JobContent, ProfileContent, Requirement
from app.contracts.ports import TaskContext
from app.intake import GatewayIntake, IntakeError, validate_profile_content
from app.llm import GatewayError
from app.platform.errors import ProfileValidationError
from app.platform.validation import validate_profile
from app.scoring import assess_requirements, calculate_score
from app.scoring.errors import ScoringError
from tests.intake.test_gateway_intake import StubGateway


def education(quote, *, attribute_quote=None, year="2027"):
    return ProfileContent(
        overview="合成教育记录",
        as_of_month="2026-11",
        facts=[
            dict(
                id="f1",
                kind="education",
                label="金融硕士",
                value="master",
                polarity="positive",
                application="claimed",
                start_month="2025-09",
                end_month=None,
                completed=False,
                evidence_ids=["e1"],
                attributes=[
                    dict(name="graduation_year", value=year, quote=attribute_quote or quote)
                ],
            )
        ],
        evidence=[
            dict(id="e1", source_type="manual", source_id="synthetic", quote=quote, locator=None)
        ],
    )


def job(*, criteria=False):
    requirement = Requirement(
        id="r1",
        quote="提供毕业时间",
        category="education",
        importance="must",
        operator="criteria" if criteria else "has_evidence",
        target="提供毕业时间",
        subject=None,
        ignored=False,
        ignore_reason=None,
        condition={
            "any_of": [
                dict(
                    scope="profile",
                    all_of=[
                        dict(
                            field="graduation_year",
                            comparison="exists",
                            value="graduation_year",
                            quote="提供毕业时间",
                        )
                    ],
                )
            ]
        }
        if criteria
        else None,
    )
    return JobContent(
        title="合成岗位", company_name=None, company_context="", requirements=[requirement]
    )


@pytest.mark.parametrize(
    "quote,attribute_quote",
    [
        ("2027 年 6 月课程结束，毕业时间尚未确定", "2027 年 6 月课程结束"),
        ("2027年6月课程结束，毕业时间尚未确定", None),
        ("2027年6月学期结束", None),
        ("2027年6月结业", None),
        ("2027年6月毕业设计结束", None),
        ("2027年6月毕业论文答辩", None),
        ("2027年6月硕士毕业论文答辩", None),
        ("2027年6月硕士毕业设计结束", None),
        ("预计2028年6月毕业", None),
        ("2027年9月入学，毕业时间待定", None),
        ("不是2027年6月毕业", "2027年6月毕业"),
        ("如果2027年6月毕业则可到岗", "2027年6月毕业"),
        ("原计划2027年6月毕业，现已延期", "2027年6月毕业"),
        ("2027年6月毕业，现已延期", "2027年6月毕业"),
        ("2027年6月毕业，但已延期", "2027年6月毕业"),
        ("预计2027年6月毕业，尚未确定", "2027年6月毕业"),
        ("课程结束，将于2027年6月因休学离校", None),
        ("课程结束，将于2027年6月退学离校", None),
        ("2027届别尚未确定", "2027届"),
        ("我不属于2027届", "2027届"),
        ("非2027届学生", "2027届"),
        ("Course ends in 2027; graduation date unknown", None),
        ("Not graduating in 2027", "graduating in 2027"),
    ],
)
def test_unrelated_or_uncertain_year_is_rejected_before_extraction_and_save(quote, attribute_quote):
    profile = education(quote, attribute_quote=attribute_quote)
    before = profile.model_dump()
    with pytest.raises(IntakeError) as extracted:
        validate_profile_content(profile, {"synthetic": quote}, today=date(2026, 11, 7))
    assert extracted.value.code == "INVALID_FACT_ATTRIBUTE"
    with pytest.raises(ProfileValidationError) as saved:
        validate_profile(profile, "2026-11")
    assert saved.value.reason_code == "SCHEMA_INVALID"
    assert profile.model_dump() == before


@pytest.mark.parametrize(
    "quote",
    [
        "2027年毕业",
        "预计2027年6月毕业",
        "预计毕业年份：2027",
        "毕业时间为2027.06",
        "2027-06（预计毕业）",
        "2027年6月30日毕业",
        "毕业日期：2027.06（预计）",
        "金融硕士（2027届）",
        "2027届毕业生",
        "课程结束，将于2027年6月离校",
        "Expected graduation: 2027",
        "Expected to graduate in June 2027",
        "Graduated in 2027",
        "Class of 2027",
        "预计2027年6月毕业，GPA未提供",
        "预计2027年6月毕业，实习延期",
        "尚未毕业，预计2027年6月毕业",
        "2027年6月毕业（预计）",
        "2027年6月硕士毕业",
    ],
)
def test_explicit_year_cohort_and_normal_course_completion_survive_all_guards(quote):
    profile = education(quote)
    before = profile.model_dump()
    validate_profile_content(profile, {"synthetic": quote}, today=date(2026, 11, 7))
    validate_profile(profile, "2026-11")
    for criteria in (False, True):
        assessment = assess_requirements(profile, job(criteria=criteria), "matcher-v3")[0]
        assert assessment.status == "met" and assessment.evidence_ids == ["e1"]
    assert profile.model_dump() == before  # No inferred month or completed degree.


@pytest.mark.parametrize("criteria", [False, True])
def test_bad_existing_year_cannot_bypass_v3_via_presence_or_criteria(criteria):
    profile = education("2027年6月课程结束，毕业时间尚未确定")
    before = profile.model_dump()
    with pytest.raises(ScoringError) as rejected:
        assess_requirements(profile, job(criteria=criteria), "matcher-v3")
    assert rejected.value.code == "INVALID_SCORING_INPUT"
    assert profile.model_dump() == before


def test_legacy_v2_replay_does_not_reinterpret_existing_year_attributes():
    profile = education("2027年6月课程结束，毕业时间尚未确定")
    before = profile.model_dump()
    result = assess_requirements(profile, job(criteria=True), "matcher-v2")[0]
    assert result.status == "met" and result.evidence_ids == ["e1"]
    assert profile.model_dump() == before


def test_gateway_extraction_rejects_a_synthetic_model_response_locally():
    quote = "2027 年 6 月课程结束，毕业时间尚未确定"
    profile = education(quote, attribute_quote="2027 年 6 月课程结束")
    gateway = StubGateway({"profile_extract": profile.model_dump(mode="json")})
    intake = GatewayIntake(gateway, source_id="synthetic", today=date(2026, 11, 7))
    with pytest.raises(IntakeError) as rejected:
        asyncio.run(
            intake.build_profile(quote, "manual", context=TaskContext(model_id="demo-model-a"))
        )
    assert rejected.value.code == "INVALID_FACT_ATTRIBUTE"
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("task", ["profile_extract", "profile_chat"])
def test_validated_gateway_checks_graduation_context_for_extraction_and_chat(task):
    class ValidatedStub(StubGateway):
        async def generate_validated(self, *args, validate_output, **kwargs):
            result = await self.generate_structured(*args, **kwargs)
            validate_output(result.data)
            return result

    quote = "2027年6月课程结束，毕业时间尚未确定"
    profile = education(quote)
    if task == "profile_chat":
        profile.evidence[0].source_type = "message"
    payload = profile.model_dump(mode="json")
    if task == "profile_chat":
        payload = {"assistant_message": "请补充毕业时间。", "profile_content": payload}
    gateway = ValidatedStub({task: payload})
    intake = GatewayIntake(gateway, source_id="synthetic", today=date(2026, 11, 7))
    context = TaskContext(model_id="demo-model-a")
    empty = ProfileContent(overview="", as_of_month="2026-11", facts=[], evidence=[])
    with pytest.raises(GatewayError) as rejected:
        asyncio.run(
            intake.build_profile(quote, "manual", context=context)
            if task == "profile_extract"
            else intake.advance_conversation(quote, empty, [], context=context)
        )
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"
    assert rejected.value.reason_code == "STRUCTURED_ATTRIBUTE_INVALID"
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("quote", ["预计2027年6月毕业", "课程结束，将于2027年6月离校"])
def test_same_event_guard_is_used_for_the_read_only_end_month_projection(quote):
    profile = education(quote)
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    before = profile.model_dump()
    assert assess_requirements(profile, job(), "matcher-v3")[0].status == "met"
    assert profile.model_dump() == before


@pytest.mark.parametrize(
    "quote,expected",
    [
        ("2027年6月毕业，但已延期", "unknown"),
        ("预计2027年6月毕业，尚未确定", "unknown"),
        ("2027年6月毕业（预计）", "met"),
        ("2027年6月硕士毕业", "met"),
    ],
)
def test_d_rereview_dates_pass_profile_guards_and_keep_the_correct_score(quote, expected):
    profile = education(quote)
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    before = profile.model_dump()
    validate_profile_content(profile, {"synthetic": quote}, today=date(2026, 11, 7))
    validate_profile(profile, "2026-11")
    result = assess_requirements(profile, job(), "matcher-v3")
    assert result[0].status == expected and result[0].evidence_ids == ["e1"]
    assert calculate_score(result, "coverage-v3").score == (100 if expected == "met" else 0)
    assert profile.model_dump() == before


@pytest.mark.parametrize(
    "quote",
    [
        "2027年6月离校，课程结束时间尚未确定",
        "2027年6月离校，2028年课程结束",
        "2028年课程结束，将于2027年6月离校",
        "课程结束时间待定，将于2027年6月离校",
        "课程结束，将于2027年6月离校，但2028年课程结束",
        "2027年6月30日课程结束，将于2027年6月1日离校",
        "2027年6月毕业，但实际已延期",
        "2027年6月毕业，但尚未确认",
        "2027年6月毕业，日期已经推迟",
        "2027年6月毕业，不过目前具体日期仍然未能确认",
        "2027年6月毕业，实际时间已经推迟至2028年",
    ],
)
def test_uncertain_completion_or_adjacent_schedule_modifiers_cannot_grant_credit(quote):
    profile = education(quote)
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    before = profile.model_dump()
    validate_profile_content(profile, {"synthetic": quote}, today=date(2026, 11, 7))
    validate_profile(profile, "2026-11")
    result = assess_requirements(profile, job(), "matcher-v3")
    assert result[0].status == "unknown" and result[0].evidence_ids == ["e1"]
    assert calculate_score(result, "coverage-v3").score == 0
    assert profile.model_dump() == before
    with pytest.raises(IntakeError):
        validate_profile_content(education(quote), {"synthetic": quote}, today=date(2026, 11, 7))


@pytest.mark.parametrize(
    "quote,attribute_quote",
    [
        ("2027年6月毕业（全日制）", "2027年6月毕业"),
        ("2027年6月毕业（非全日制）", "2027年6月"),
        ("预计2027年6月毕业", "2027年6月"),
        ("预计 2027 年 6 月毕业（全日制）", "2027 年 6 月"),
        ("课程结束，将于2027年6月离校", "2027年6月"),
        ("2027年5月课程结束，将于2027年6月离校", "2027年6月"),
        ("完成课程后于2027年6月离校", "2027年6月"),
        ("2027年6月1日课程结束，将于2027年6月30日离校", "2027年6月30日"),
        ("2027年6月毕业，但实习日期已经推迟", "2027年6月"),
        ("预计2027年6月毕业\n实习延期", "2027年6月"),
    ],
)
def test_linked_short_quotes_and_qualifiers_remain_editable_and_scorable(quote, attribute_quote):
    profile = education(quote, attribute_quote=attribute_quote)
    before = profile.model_dump()
    validate_profile_content(profile, {"synthetic": quote}, today=date(2026, 11, 7))
    validate_profile(profile, "2026-11")
    for version in ("matcher-v2", "matcher-v3"):
        assert assess_requirements(profile, job(criteria=True), version)[0].status == "met"
    assert profile.model_dump() == before
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    assert assess_requirements(profile, job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "quote,attribute_quote",
    [
        ("2027年6月课程结束，2027年9月毕业", "2027年6月"),
        ("2027年6月课程结束，2028年6月毕业", "2027年6月"),
        ("2027年6月课程结束，2027年6月毕业", "2027年6月"),
        ("2027年6月毕业（尚未确认）", "2027年6月"),
        ("2027年6月毕业（论文答辩）", "2027年6月"),
    ],
)
def test_short_quote_must_identify_the_graduation_event_not_another_date(quote, attribute_quote):
    profile = education(quote, attribute_quote=attribute_quote)
    with pytest.raises(IntakeError):
        validate_profile_content(profile, {"synthetic": quote}, today=date(2026, 11, 7))


def test_user_can_edit_unrelated_fields_without_rewriting_a_legacy_short_quote():
    from tests.platform.test_api import app_for, check, clients, post, session

    async def run():
        async with clients(app_for()) as (client,):
            await session(client)
            profile = education("预计2027年6月毕业（全日制）", attribute_quote="2027年6月")
            saved = check(
                await post(client, "/api/v1/profiles", {"content": profile.model_dump()}),
                201,
                "Profile",
            )
            profile.overview = "只更新简介的合成档案"
            updated = check(
                await client.put(
                    f"/api/v1/profiles/{saved['id']}",
                    json={"base_version": 1, "content": profile.model_dump()},
                ),
                200,
                "Profile",
            )
            assert updated["version"] == 2
            assert updated["content"]["facts"] == saved["content"]["facts"]
            assert updated["content"]["evidence"] == saved["content"]["evidence"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "quotes",
    [
        ["预计2027年6月毕业，实际毕业时间调整为2028年6月"],
        ["预计2027年6月毕业", "实际毕业时间调整为2028年6月"],
    ],
)
def test_conflicting_graduation_years_do_not_project_or_validate_attribute(quotes):
    from app.graduation_evidence import explicit_graduation_quote, graduation_attribute_supported

    assert explicit_graduation_quote(quotes, "2027-06") is None
    assert not graduation_attribute_supported("2027年6月", "2027", quotes)
    profile = education(quotes[0])
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    if len(quotes) > 1:
        profile.evidence.append(
            profile.evidence[0].model_copy(update={"id": "e2", "quote": quotes[1]})
        )
        profile.facts[0].evidence_ids.append("e2")
    validate_profile(profile, "2026-11")
    assert assess_requirements(profile, job(), "matcher-v3")[0].status == "unknown"
    profile.facts[0].attributes = (
        education(quotes[0], attribute_quote="2027年6月").facts[0].attributes
    )
    with pytest.raises(ProfileValidationError):
        validate_profile(profile, "2026-11")
    with pytest.raises(ScoringError):
        assess_requirements(profile, job(criteria=True), "matcher-v3")


@pytest.mark.parametrize("other", ["2028年6月实习", "2028年6月入职", "参加2028年毕业论文研讨会"])
def test_unrelated_year_does_not_conflict_with_graduation(other):
    from app.graduation_evidence import explicit_graduation_quote, graduation_attribute_supported

    quote = "预计2027年6月毕业，" + other
    assert explicit_graduation_quote([quote], "2027-06") == quote
    assert graduation_attribute_supported("2027年6月", "2027", [quote])


@pytest.mark.parametrize("split", [False, True, "same_clause"])
@pytest.mark.parametrize("attribute", [False, True])
def test_distinct_degree_graduations_in_shared_evidence_are_not_conflicts(split, attribute):
    quotes = ["2024年本科毕业", "预计2027年6月硕士毕业"]
    profile = education("，".join(quotes), attribute_quote="2027年6月硕士毕业")
    if split == "same_clause":
        profile.evidence[0].quote = "并".join(quotes)
    elif split:
        profile.evidence[0].quote = quotes[0]
        profile.evidence.append(
            profile.evidence[0].model_copy(update={"id": "e2", "quote": quotes[1]})
        )
        profile.facts[0].evidence_ids.append("e2")
    if not attribute:
        profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    before = profile.model_dump()
    validate_profile(profile, "2026-11")
    validate_profile_content(
        profile,
        {"synthetic": "，".join(e.quote for e in profile.evidence)},
        today=date(2026, 11, 7),
    )
    assert assess_requirements(profile, job(), "matcher-v3")[0].status == "met"
    assert profile.model_dump() == before


@pytest.mark.parametrize("followup", ["实际调整为2028年6月", "实际毕业时间变更为2028年6月"])
@pytest.mark.parametrize("attribute", [False, True])
def test_same_graduation_event_adjustment_needs_confirmation(followup, attribute):
    profile = education("预计2027年6月毕业，" + followup, attribute_quote="2027年6月")
    if attribute:
        with pytest.raises(ProfileValidationError):
            validate_profile(profile, "2026-11")
        with pytest.raises(ScoringError):
            assess_requirements(profile, job(criteria=True), "matcher-v3")
    else:
        profile.facts[0].attributes = []
        profile.facts[0].end_month = "2027-06"
        validate_profile(profile, "2026-11")
        assert assess_requirements(profile, job(), "matcher-v3")[0].status == "unknown"


def test_irrelevant_identifiers_do_not_multiply_graduation_scans(monkeypatch):
    import time

    import app.graduation_evidence as evidence_module

    quote = "预计2027年6月硕士毕业。编号：" + " ".join(str(i) for i in range(1000, 1300))
    profile = education(quote, attribute_quote="2027年6月硕士毕业")
    profile.facts = [profile.facts[0].model_copy(update={"id": f"f{i}"}) for i in range(10)]
    original = evidence_module._graduation_spans
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence_module, "_graduation_spans", counted)
    started = time.perf_counter()
    validate_profile(profile, "2026-11")
    elapsed = time.perf_counter() - started
    assert len(calls) <= 20  # Work depends on facts/evidence, never distinct identifiers.
    assert elapsed < 2  # Generous guard against the reported 22-second synchronous stall.


@pytest.mark.parametrize(
    "tail",
    [
        "实习日期调整为2028年6月",
        "入职时间变更为2028年6月",
        "实习时间2026年6月，实际调整为2028年6月",
        "2024年本科毕业，实际调整为2025年6月",
        "2024年本科毕业，实际本科毕业时间变更为2025年6月",
    ],
)
def test_adjustments_to_other_events_do_not_change_master_graduation(tail):
    profile = education("预计2027年6月硕士毕业，" + tail, attribute_quote="2027年6月硕士毕业")
    validate_profile(profile, "2026-11")
    assert assess_requirements(profile, job(criteria=True), "matcher-v3")[0].status == "met"
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    assert assess_requirements(profile, job(), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "value,quote",
    [
        ("master", "预计2027年6月本科毕业"),
        (None, "2024年本科毕业，预计2027年6月硕士毕业"),
        ("master", "2024年硕士毕业，预计2027年6月硕士毕业"),
    ],
)
def test_ambiguous_or_other_degree_cannot_supply_current_graduation(value, quote):
    profile = education(quote, attribute_quote="2027年6月")
    profile.facts[0].value = value
    with pytest.raises(ProfileValidationError):
        validate_profile(profile, "2026-11")
    profile.facts[0].attributes = []
    profile.facts[0].end_month = "2027-06"
    validate_profile(profile, "2026-11")
    assert assess_requirements(profile, job(), "matcher-v3")[0].status == "unknown"


def split_graduation_adjustment(*, other_source=False, reverse=False):
    profile = education("预计2027年6月硕士毕业", attribute_quote="2027年6月硕士毕业")
    profile.evidence.append(
        profile.evidence[0].model_copy(
            update={
                "id": "e2",
                "quote": "实际调整为2028年6月",
                "source_id": "other" if other_source else "synthetic",
            }
        )
    )
    profile.facts[0].evidence_ids.append("e2")
    if reverse:
        profile.evidence.reverse()
    return profile


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("entry", ["extract", "save", "score", "projection"])
def test_linked_source_adjustment_survives_evidence_splitting(reverse, entry):
    profile = split_graduation_adjustment(reverse=reverse)
    if entry == "extract":
        with pytest.raises(IntakeError):
            validate_profile_content(
                profile,
                {"synthetic": "预计2027年6月硕士毕业，实际调整为2028年6月"},
                today=date(2026, 11, 7),
            )
    elif entry == "save":
        with pytest.raises(ProfileValidationError):
            validate_profile(profile, "2026-11")
    elif entry == "score":
        target = job(criteria=True)
        atom = target.requirements[0].condition.any_of[0].all_of[0]
        atom.comparison, atom.value, atom.quote = "eq", "2027", "2027年毕业"
        target.requirements[0].quote = target.requirements[0].target = "2027年毕业"
        from app.structured_fields import validate_condition

        validate_condition(target.requirements[0])
        with pytest.raises(ScoringError):
            assess_requirements(profile, target, "matcher-v3")
    else:
        profile.facts[0].attributes = []
        profile.facts[0].end_month = "2027-06"
        validate_profile(profile, "2026-11")
        result = assess_requirements(profile, job(), "matcher-v3")
        assert result[0].status == "unknown"
        assert calculate_score(result, "coverage-v3").score == 0


def test_unrelated_source_is_not_concatenated_to_graduation_event():
    profile = split_graduation_adjustment(other_source=True)
    validate_profile(profile, "2026-11")
    assert assess_requirements(profile, job(criteria=True), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize(
    "tail",
    [
        ["实习时间调整为2028年6月"],
        ["2024年本科毕业", "实际调整为2025年6月"],
        ["实习时间2026年6月", "实际调整为2028年6月"],
    ],
)
def test_split_other_events_do_not_change_master_date(tail):
    profile = education("预计2027年6月硕士毕业", attribute_quote="2027年6月硕士毕业")
    for index, quote in enumerate(tail, 2):
        eid = f"e{index}"
        profile.evidence.append(profile.evidence[0].model_copy(update={"id": eid, "quote": quote}))
        profile.facts[0].evidence_ids.append(eid)
    validate_profile(profile, "2026-11")
    assert assess_requirements(profile, job(criteria=True), "matcher-v3")[0].status == "met"


@pytest.mark.parametrize("boundary", ["source_type", "unlinked_fact"])
def test_fragment_context_respects_type_and_fact_boundaries(boundary):
    profile = split_graduation_adjustment()
    if boundary == "source_type":
        profile.evidence[1].source_type = "message"
    else:
        profile.facts[0].evidence_ids = ["e1"]
    validate_profile(profile, "2026-11")
    assert assess_requirements(profile, job(criteria=True), "matcher-v3")[0].status == "met"
