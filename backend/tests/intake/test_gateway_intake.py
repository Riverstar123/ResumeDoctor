"""GatewayIntake：提示词组织、网关调用与结果校验。

这里用可控替身网关（而非 M5 的 FakeModelGateway）精确指定「输入 → 输出」的对应
关系：假网关在 profile_chat 上固定返回合成档案，无法体现「证据来自用户本轮的话」，
跨模块一致性由 tests/llm/test_cross_module.py 覆盖。
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from app.contracts import Message, ModelMetadata, ProfileContent
from app.contracts.ports import StructuredResult, TaskContext
from app.intake import (
    HISTORY_LIMIT,
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCE_ID,
    SYNTHETIC_SOURCE_TEXT,
    GatewayIntake,
    IntakeError,
    synthetic_profile_content,
)
from app.intake.prompts import PROFILE_CHAT_PROMPT, PROFILE_EXTRACT_PROMPT
from app.llm.schemas import task_output_schema

CONTEXT = TaskContext(model_id="demo-model-a")
METADATA = ModelMetadata(
    model_id="demo-model-a",
    provider="fake",
    model="synthetic-fake-v1",
    prompt_version="profile-v1",
    gateway_config_version="fake-gateway-v1",
    generated_at="2026-10-15T00:00:00Z",
)


class StubGateway:
    """按调用方要求返回预设数据的替身网关。"""

    is_fake = True

    def __init__(self, payloads: Mapping[str, Any] | None = None, error: Exception | None = None):
        self.payloads = dict(payloads or {})
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate_structured(
        self, task_name, prompt_context, output_schema, timeout_seconds, *, context
    ):
        self.calls.append(
            {
                "task_name": task_name,
                "prompt_context": dict(prompt_context),
                "output_schema": output_schema,
                "timeout_seconds": timeout_seconds,
                "context": context,
            }
        )
        if self.error is not None:
            raise self.error
        return StructuredResult(data=self.payloads[task_name], model_metadata=METADATA)


def chat_payload(user_text: str, *, message_id: str = SYNTHETIC_SOURCE_ID) -> dict:
    """构造一份「证据来自本轮用户发言」的对话结果。"""
    return {
        "assistant_message": "你在其中负责哪一部分？",
        "profile_content": {
            "overview": "合成对话档案。",
            "as_of_month": "2026-09",
            "facts": [
                {
                    "id": "f1",
                    "kind": "project",
                    "label": "数据清洗",
                    "value": None,
                    "polarity": "positive",
                    "application": "applied",
                    "start_month": None,
                    "end_month": None,
                    "completed": None,
                    "evidence_ids": ["e1"],
                }
            ],
            "evidence": [
                {
                    "id": "e1",
                    "source_type": "message",
                    "source_id": message_id,
                    "quote": user_text,
                    "locator": None,
                }
            ],
        },
    }


def user_message(content: str, index: int) -> Message:
    return Message(
        id=f"00000000-0000-4000-8000-0000000000{index:02d}",
        role="user",
        content=content,
        created_at="2026-10-15T00:00:00Z",
    )


def empty_profile() -> ProfileContent:
    return ProfileContent(overview="", as_of_month="2026-09", facts=[], evidence=[])


# --- build_profile ----------------------------------------------------------


def test_build_profile_returns_validated_content():
    gateway = StubGateway({"profile_extract": synthetic_profile_content().model_dump(mode="json")})
    intake = GatewayIntake(gateway)

    result = asyncio.run(intake.build_profile(SYNTHETIC_SOURCE_TEXT, "manual", context=CONTEXT))

    assert [fact.id for fact in result.facts] == ["f1", "f2", "f3"]


def test_build_profile_sends_frozen_schema_and_prompt():
    gateway = StubGateway({"profile_extract": synthetic_profile_content().model_dump(mode="json")})
    intake = GatewayIntake(gateway)

    asyncio.run(intake.build_profile(SYNTHETIC_SOURCE_TEXT, "manual", context=CONTEXT))

    call = gateway.calls[0]
    assert call["task_name"] == "profile_extract"
    # 网关要求调用方传入冻结结构（app/llm/schemas.py）。
    assert call["output_schema"] == task_output_schema("profile_extract")
    assert call["timeout_seconds"] == 45.0
    assert call["prompt_context"]["prompt"] == PROFILE_EXTRACT_PROMPT
    assert call["prompt_context"]["source_id"] == SYNTHETIC_SOURCE_ID
    assert call["prompt_context"]["source_text"] == SYNTHETIC_SOURCE_TEXT


def test_build_profile_rejects_evidence_outside_source():
    payload = synthetic_profile_content().model_dump(mode="json")
    payload["evidence"][0]["quote"] = "精通 Python"

    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(StubGateway({"profile_extract": payload})).build_profile(
                SYNTHETIC_SOURCE_TEXT, "manual", context=CONTEXT
            )
        )
    assert error.value.code == "QUOTE_NOT_IN_SOURCE"


# --- advance_conversation ---------------------------------------------------


def test_advance_conversation_returns_message_and_profile():
    user_text = "我在课程项目里做过数据清洗。"
    gateway = StubGateway({"profile_chat": chat_payload(user_text)})

    result = asyncio.run(
        GatewayIntake(gateway).advance_conversation(user_text, empty_profile(), [], context=CONTEXT)
    )

    assert result.assistant_message
    assert [fact.id for fact in result.profile_content.facts] == ["f1"]


def test_advance_conversation_sends_only_recent_history():
    history = [user_message(f"第 {index} 条", index) for index in range(HISTORY_LIMIT + 5)]
    user_text = "我又做了一个新项目。"
    gateway = StubGateway({"profile_chat": chat_payload(user_text)})

    asyncio.run(
        GatewayIntake(gateway).advance_conversation(
            user_text, empty_profile(), history, context=CONTEXT
        )
    )

    sent = gateway.calls[0]["prompt_context"]["history_user_messages"]
    assert len(sent) == HISTORY_LIMIT
    assert sent[-1] == {
        "source_id": history[-1].id,
        "content": f"第 {HISTORY_LIMIT + 4} 条",
    }
    assert gateway.calls[0]["prompt_context"]["prompt"] == PROFILE_CHAT_PROMPT


def test_advance_conversation_accepts_evidence_from_history():
    history = [user_message("我做过一个 Python 项目。", 1)]
    user_text = "就是这个项目。"
    payload = chat_payload("我做过一个 Python 项目。", message_id=history[0].id)
    gateway = StubGateway({"profile_chat": payload})

    result = asyncio.run(
        GatewayIntake(gateway).advance_conversation(
            user_text, empty_profile(), history, context=CONTEXT
        )
    )

    assert result.profile_content.evidence[0].source_id == history[0].id


# --- extract_job ------------------------------------------------------------


def test_extract_job_validates_quote_against_raw_text():
    payload = {
        "title": "数据开发",
        "company_name": None,
        "company_context": "",
        "requirements": [
            {
                "id": "r1",
                "quote": "精通 Kubernetes 并有大厂经验",
                "category": "skill",
                "importance": "must",
                "operator": "has_skill",
                "target": "Kubernetes",
                "ignored": False,
                "ignore_reason": None,
                "subject": None,
            }
        ],
    }

    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(StubGateway({"job_extract": payload})).extract_job(
                SYNTHETIC_JOB_RAW_TEXT, "", context=CONTEXT
            )
        )
    assert error.value.code == "QUOTE_NOT_IN_SOURCE"


# --- 错误与未实现部分 -------------------------------------------------------


def test_gateway_error_is_not_swallowed():
    """网关错误码原样上抛，由 M2 统一映射（本模块不改写错误）。"""
    from app.llm import GatewayError

    gateway = StubGateway(error=GatewayError("MODEL_TIMEOUT", "模型调用超过单次时限"))

    with pytest.raises(GatewayError) as error:
        asyncio.run(GatewayIntake(gateway).extract_job(SYNTHETIC_JOB_RAW_TEXT, "", context=CONTEXT))
    assert error.value.code == "MODEL_TIMEOUT"


def test_extract_document_rejects_an_invalid_stream():
    intake = GatewayIntake(StubGateway())
    with pytest.raises(IntakeError) as error:
        asyncio.run(intake.extract_document(None, "application/pdf"))
    assert error.value.code == "DOCUMENT_PARSE_FAILED"


def test_prompt_versions_match_the_gateway_catalog():
    """M3 维护提示词内容与版本，M5 目录记录同一批版本；两侧漂移必须立刻暴露。

    任务快照记录的是 M5 目录里的版本号，若 M3 升级版本而 M5 未同步，
    历史记录会对应到错误的内容版本。
    """
    from app.intake.prompts import (
        JOB_EXTRACT_VERSION,
        PROFILE_CHAT_VERSION,
        PROFILE_EXTRACT_VERSION,
    )
    from app.llm import PROMPT_VERSIONS

    assert PROFILE_EXTRACT_VERSION == PROMPT_VERSIONS["profile_extract"]
    assert PROFILE_CHAT_VERSION == PROMPT_VERSIONS["profile_chat"]
    assert JOB_EXTRACT_VERSION == PROMPT_VERSIONS["job_extract"]


def test_profile_content_model_round_trip_is_stable():
    """确认测试使用的合成档案本身合法，避免测试断言依赖坏数据。"""
    content = ProfileContent.model_validate(synthetic_profile_content().model_dump())
    assert content.as_of_month == "2026-09"
