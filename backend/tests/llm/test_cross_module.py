"""跨模块验收：假网关的档案/JD 输出必须通过既有 M3 校验与冻结样例。

评审 P2 复现的问题是：网关输出的 source_id/quote 与 M3 合成端口、`docs/examples`
不一致，C 用既有演示原文接入时 M3 校验报 UNKNOWN_SOURCE / QUOTE_NOT_IN_SOURCE。
这里把三者钉在一起，任何一侧漂移都会失败。
"""

import asyncio
import json
from pathlib import Path

from app.contracts import JobContent, ProfileContent
from app.contracts.ports import TaskContext
from app.intake import (
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCE_ID,
    SYNTHETIC_SOURCE_TEXT,
    SYNTHETIC_SOURCES,
    SyntheticIntake,
    validate_job_content,
    validate_profile_content,
)
from app.llm import FakeModelDirectory, FakeModelGateway, task_output_schema
from app.llm import synthetic as gateway_synthetic

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"


async def _no_sleep(_seconds: float) -> None:
    return None


def _run(task_name: str, prompt_context: dict | None = None):
    gateway = FakeModelGateway(
        FakeModelDirectory(), sleep=_no_sleep, clock=lambda: "2026-10-14T00:00:00Z"
    )
    return asyncio.run(
        gateway.generate_structured(
            task_name,
            prompt_context or {},
            task_output_schema(task_name),
            1.0,
            context=TaskContext(model_id="demo-model-a"),
        )
    )


def test_gateway_profile_output_passes_m3_validation():
    data = _run("profile_extract").data
    content = ProfileContent.model_validate(dict(data))
    # 评审复现的命令：用 M3 的来源表校验网关的档案输出，必须不抛异常。
    validate_profile_content(content, SYNTHETIC_SOURCES)


def test_gateway_job_output_passes_m3_validation():
    data = _run("job_extract").data
    content = JobContent.model_validate(dict(data))
    validate_job_content(content, SYNTHETIC_JOB_RAW_TEXT)


def test_gateway_synthetic_sources_match_m3_constants_verbatim():
    assert gateway_synthetic.SYNTHETIC_SOURCE_ID == SYNTHETIC_SOURCE_ID
    assert gateway_synthetic.SYNTHETIC_SOURCE_TEXT == SYNTHETIC_SOURCE_TEXT
    assert gateway_synthetic.SYNTHETIC_JOB_RAW_TEXT == SYNTHETIC_JOB_RAW_TEXT
    assert gateway_synthetic.SYNTHETIC_ASSISTANT_MESSAGE == SyntheticIntake().assistant_message


def test_gateway_profile_payload_matches_the_frozen_example():
    example = json.loads((EXAMPLES / "profile.json").read_text(encoding="utf-8"))
    assert gateway_synthetic.synthetic_profile_payload() == example["content"]


def test_gateway_job_payload_matches_the_frozen_example():
    example = json.loads((EXAMPLES / "job.json").read_text(encoding="utf-8"))
    assert gateway_synthetic.synthetic_job_payload() == example["content"]


def test_gateway_chat_draft_also_passes_m3_validation():
    # 对话轮次返回的档案草稿与一次性提取走同一份素材，同样要能通过校验。
    data = _run("profile_chat").data
    content = ProfileContent.model_validate(dict(data["profile_content"]))
    validate_profile_content(content, SYNTHETIC_SOURCES)
