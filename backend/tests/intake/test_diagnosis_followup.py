"""Target metadata is not evidence; question-only calls are strictly read-only."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from app.contracts import Gap, ResourceVersion
from app.contracts.ports import DiagnosisFocusContext, StructuredResult
from app.intake import GatewayIntake, IntakeError
from app.intake.synthetic import synthetic_job_content, synthetic_profile_content
from app.scoring import ScoringService
from tests.intake.test_gateway_intake import CONTEXT, METADATA, StubGateway


@pytest.fixture
def focus():
    profile, job = synthetic_profile_content(), synthetic_job_content()
    assessment = ScoringService().assess_requirements(profile, job, "matcher-v1")[1]
    return DiagnosisFocusContext(
        diagnosis_id=str(uuid4()),
        item_id=str(uuid4()),
        profile=ResourceVersion(id=str(uuid4()), version=1),
        job=ResourceVersion(id=str(uuid4()), version=1),
        job_title=job.title,
        requirement=job.requirements[1],
        assessment=assessment,
        gap=Gap(
            requirement_id="r2",
            kind="partial_gap",
            description="核实 SQL 应用经历",
            evidence_ids=["e2"],
        ),
    )


def run(focus, payload, *, questions=True, user_text="启动指令不应成为事实"):
    gateway = StubGateway(
        {"profile_chat": {"assistant_message": "是否实际使用过 SQL？", "profile_content": payload}}
    )
    result = asyncio.run(
        GatewayIntake(gateway, source_id="current-user-message").advance_conversation(
            user_text,
            synthetic_profile_content(),
            [],
            context=CONTEXT,
            diagnosis_focus=focus,
            questions_only=questions,
        )
    )
    return result, gateway.calls[0]["prompt_context"]


def test_question_stage_keeps_profile_and_excludes_launch_text_and_source(focus):
    before = synthetic_profile_content()
    result, prompt = run(focus, before.model_dump(mode="json"))
    assert result.profile_content == before
    assert prompt["user_text"] == "" and "message_source_id" not in prompt
    assert prompt["diagnosis_focus"]["requirement"]["quote"] == focus.requirement.quote
    assert prompt["diagnosis_focus"]["assessment"]["status"] == "partial"
    assert "不是候选人的事实" in prompt["prompt"]


@pytest.mark.parametrize("change", ["overview", "fact", "evidence", "jd_source"])
def test_question_stage_rejects_any_profile_change_and_job_quote_as_fact(focus, change):
    payload = synthetic_profile_content().model_dump(mode="json")
    if change == "overview":
        payload["overview"] = "未经用户补充的新概括"
    elif change == "fact":
        payload["facts"][1]["polarity"] = "negative"
    elif change == "evidence":
        payload["evidence"][1]["quote"] = "熟练掌握 SQL。"
    else:
        payload["evidence"].append(
            {
                "id": "e-jd",
                "source_type": "message",
                "source_id": focus.job.id,
                "quote": focus.requirement.quote,
                "locator": None,
            }
        )
    with pytest.raises(IntakeError):
        run(focus, payload)


def test_answer_cannot_turn_job_context_into_a_user_source(focus):
    payload = synthetic_profile_content().model_dump(mode="json")
    payload["evidence"].append(
        {
            "id": "e-jd",
            "source_type": "message",
            "source_id": "current-user-message",
            "quote": focus.requirement.quote,
            "locator": None,
        }
    )
    with pytest.raises(IntakeError) as error:
        run(focus, payload, questions=False, user_text="我暂时没有更多信息。")
    assert error.value.code == "QUOTE_NOT_IN_SOURCE"


def test_explicit_denial_is_retained_without_new_user_evidence(focus):
    previous = synthetic_profile_content()
    previous.facts[1].polarity = "negative"
    payload = previous.model_dump(mode="json")
    payload["facts"][1]["polarity"] = "positive"
    gateway = StubGateway(
        {"profile_chat": {"assistant_message": "补充", "profile_content": deepcopy(payload)}}
    )
    with pytest.raises(IntakeError):
        asyncio.run(
            GatewayIntake(gateway, source_id="new-user").advance_conversation(
                "只是继续提问，没有更正先前否认。",
                previous,
                [],
                context=CONTEXT,
                diagnosis_focus=focus,
            )
        )


@pytest.mark.parametrize("mutation", [None, "overview", "as_of_month", "fact", "evidence"])
def test_question_stage_echoes_privacy_projection_but_restores_original_profile(focus, mutation):
    original = synthetic_profile_content()
    original.overview = "合成档案；联系 candidate@example.invalid，电话：13800138000"
    original.evidence[1].quote += " 联系 candidate@example.invalid。"
    before = original.model_dump(mode="json")

    class ProjectionEcho:
        is_fake = True

        async def generate_structured(self, name, prompt, schema, timeout, *, context):
            projected = deepcopy(prompt["profile_content"])
            assert "candidate@example.invalid" not in projected["overview"]
            assert "13800138000" not in projected["overview"]
            assert "candidate@example.invalid" not in projected["evidence"][1]["quote"]
            if mutation == "overview":
                projected["overview"] += "新增描述"
            elif mutation == "as_of_month":
                projected["as_of_month"] = "2026-08"
            elif mutation == "fact":
                projected["facts"][1]["label"] = "Kubernetes"
            elif mutation == "evidence":
                projected["evidence"][1]["quote"] += "无依据的新句子。"
            return StructuredResult(
                {"assistant_message": "请补充实际的 SQL 工作。", "profile_content": projected},
                METADATA,
            )

    call = GatewayIntake(ProjectionEcho()).advance_conversation(
        "不作为事实的启动文字",
        original,
        [],
        context=CONTEXT,
        diagnosis_focus=focus,
        questions_only=True,
    )
    if mutation is not None:
        with pytest.raises(IntakeError, match="提问阶段"):
            asyncio.run(call)
    else:
        result = asyncio.run(call)
        assert result.profile_content.model_dump(mode="json") == before
        assert result.profile_content is not original
    assert original.model_dump(mode="json") == before
