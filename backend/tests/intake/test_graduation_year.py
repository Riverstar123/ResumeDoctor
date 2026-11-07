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
