"""假网关：四类任务、结构化输出校验、输入预算与调用记录。

验证范围 T11/T19/T21 的 fake 场景（正常路径）。失败路径见 test_failures.py。
全部为合成数据，不需要 API key，也不读取任何 LLM_* 设置。
"""

import asyncio
import copy

import jsonschema
import pytest

from app.contracts import JobContent, ModelMetadata, ProfileContent, ReportContent
from app.contracts.ports import ModelGateway, TaskContext
from app.llm import FakeModelDirectory, FakeModelGateway, GatewayError, task_output_schema

FIXED_NOW = "2026-10-14T00:00:00Z"
CONTEXT = TaskContext(model_id="demo-model-a")

SCHEMAS = {
    task_name: task_output_schema(task_name)
    for task_name in (
        "profile_extract",
        "profile_chat",
        "job_extract",
        "diagnosis_report",
    )
}


async def _no_sleep(_seconds: float) -> None:
    return None


def build_gateway(**kwargs) -> FakeModelGateway:
    return FakeModelGateway(
        FakeModelDirectory(),
        sleep=_no_sleep,
        clock=lambda: FIXED_NOW,
        **kwargs,
    )


def run(
    gateway: FakeModelGateway,
    task_name: str,
    prompt_context: dict | None = None,
    schema: dict | None = None,
):
    return asyncio.run(
        gateway.generate_structured(
            task_name,
            prompt_context or {},
            schema if schema is not None else SCHEMAS[task_name],
            1.0,
            context=CONTEXT,
        )
    )


def test_gateway_satisfies_model_gateway_protocol():
    assert isinstance(build_gateway(), ModelGateway)


def test_all_four_tasks_run_in_fake_mode_without_api_key():
    gateway = build_gateway()
    profile = run(gateway, "profile_extract")
    ProfileContent.model_validate(dict(profile.data))

    assert isinstance(profile.model_metadata, ModelMetadata)
    assert profile.model_metadata.provider == "fake"
    assert profile.model_metadata.model == "synthetic-fake-v1"
    assert profile.model_metadata.prompt_version == "profile-v1"
    assert profile.model_metadata.gateway_config_version == "fake-gateway-v1"
    assert profile.model_metadata.generated_at == FIXED_NOW

    chat = run(gateway, "profile_chat")
    assert chat.data["assistant_message"]
    ProfileContent.model_validate(dict(chat.data["profile_content"]))
    assert chat.model_metadata.prompt_version == "chat-v1"

    job = run(gateway, "job_extract")
    JobContent.model_validate(dict(job.data))
    assert job.model_metadata.prompt_version == "job-v1"

    report = run(gateway, "diagnosis_report", {"score_result": _example_score()})
    ReportContent.model_validate(dict(report.data))
    assert report.model_metadata.prompt_version == "report-v1"


def test_fake_profile_quotes_are_present_in_the_synthetic_source():
    from app.llm.synthetic import (
        SYNTHETIC_SOURCE_ID,
        SYNTHETIC_SOURCE_TEXT,
        synthetic_profile_payload,
    )

    payload = synthetic_profile_payload()
    for evidence in payload["evidence"]:
        assert evidence["source_id"] == SYNTHETIC_SOURCE_ID
        assert evidence["quote"] in SYNTHETIC_SOURCE_TEXT


def test_fake_job_quotes_are_present_in_the_synthetic_job_text():
    from app.llm.synthetic import SYNTHETIC_JOB_RAW_TEXT, synthetic_job_payload

    for requirement in synthetic_job_payload()["requirements"]:
        assert requirement["quote"] in SYNTHETIC_JOB_RAW_TEXT


def test_report_gaps_follow_the_frozen_score_statuses():
    report = run(build_gateway(), "diagnosis_report", {"score_result": _example_score()}).data
    kinds = {gap["requirement_id"]: gap["kind"] for gap in report["gaps"]}
    # r1 met、r4 met 无 gap；r2 partial→partial_gap；r3 unknown→needs_evidence。
    assert kinds == {"r2": "partial_gap", "r3": "needs_evidence"}
    assert {action["requirement_id"] for action in report["actions"]} == {"r2", "r3"}
    assert all(s["requires_user_input"] for s in report["suggestions"])
    # gap 证据必须落在该条评估已有引用内，不能凭空新增。
    for gap in report["gaps"]:
        allowed = next(
            a["evidence_ids"]
            for a in _example_score()["assessments"]
            if a["requirement_id"] == gap["requirement_id"]
        )
        assert set(gap["evidence_ids"]) <= set(allowed)


def test_missing_score_yields_an_empty_but_valid_report():
    report = run(build_gateway(), "diagnosis_report", {}).data
    assert report["gaps"] == [] and report["suggestions"] == [] and report["actions"] == []
    ReportContent.model_validate(dict(report))


def test_input_over_report_limit_is_rejected_without_truncation():
    gateway = build_gateway()
    with pytest.raises(GatewayError) as error:
        run(gateway, "diagnosis_report", {"text": "x" * 20_001})
    assert error.value.code == "INPUT_TOO_LONG"
    assert gateway.calls == []


def test_input_over_extraction_limit_is_rejected():
    with pytest.raises(GatewayError) as error:
        run(build_gateway(), "job_extract", {"raw_text": "x" * 30_001})
    assert error.value.code == "INPUT_TOO_LONG"


def test_input_at_the_limit_is_accepted():
    result = run(build_gateway(), "profile_extract", {"text": "x" * 30_000})
    ProfileContent.model_validate(dict(result.data))


def test_unknown_disabled_and_mismatched_models_fail_through_the_gateway():
    gateway = build_gateway()
    with pytest.raises(GatewayError) as missing:
        asyncio.run(
            gateway.generate_structured(
                "profile_extract",
                {},
                SCHEMAS["profile_extract"],
                1.0,
                context=TaskContext(model_id="ghost"),
            )
        )
    assert missing.value.code == "MODEL_UNAVAILABLE"

    disabled = build_gateway()
    disabled.directory.disable("demo-model-a")
    with pytest.raises(GatewayError) as off:
        run(disabled, "job_extract")
    assert off.value.code == "MODEL_UNAVAILABLE"


def test_calls_record_metadata_without_raw_input_or_secrets():
    gateway = build_gateway()
    run(gateway, "profile_extract", {"resume_text": "合成敏感标记-不得出现在记录里"})
    run(gateway, "diagnosis_report", {"score_result": _example_score()})
    assert [call.task_name for call in gateway.calls] == ["profile_extract", "diagnosis_report"]
    assert all(call.outcome == "ok" and call.attempts == 1 for call in gateway.calls)
    assert all(call.model_id == "demo-model-a" for call in gateway.calls)
    assert gateway.calls[-1].prompt_version == "report-v1"
    rendered = repr(gateway.calls)
    assert "合成敏感标记" not in rendered
    assert "key" not in rendered.lower()


def test_non_mapping_output_schema_is_rejected():
    gateway = build_gateway()
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_structured(
                "profile_extract", {}, ["not", "a", "schema"], 1.0, context=CONTEXT
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_every_result_conforms_to_the_schema_the_caller_passed():
    gateway = build_gateway()
    prompts = {
        "profile_extract": {},
        "profile_chat": {},
        "job_extract": {},
        "diagnosis_report": {"score_result": _example_score()},
    }
    for task_name, prompt_context in prompts.items():
        result = run(gateway, task_name, prompt_context)
        # 用调用方实际传入的 Schema 独立校验返回数据，而不是只看网关自己的 DTO。
        jsonschema.validate(instance=dict(result.data), schema=SCHEMAS[task_name])


def test_schema_of_another_task_is_rejected_before_any_model_call():
    # 复现评审场景：把 JobContent 的 Schema 传给 profile_extract，不得返回档案并记 ok。
    gateway = build_gateway()
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_structured(
                "profile_extract", {}, JobContent.model_json_schema(), 1.0, context=CONTEXT
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert gateway.calls == []


def test_profile_chat_rejects_the_bare_profile_schema():
    # profile_chat 的输出是包装结构；只传 ProfileContent 的 Schema 不再是合法调用。
    gateway = build_gateway()
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_structured(
                "profile_chat", {}, ProfileContent.model_json_schema(), 1.0, context=CONTEXT
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert gateway.calls == []


def test_unknown_task_name_is_rejected():
    gateway = build_gateway()
    with pytest.raises(GatewayError) as error:
        run(gateway, "profile_summarize", {}, schema=ProfileContent.model_json_schema())
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert gateway.calls == []


def test_frozen_structure_without_titles_is_accepted():
    # title/description 只是文档信息；字段一致的 Schema 仍应被接受。
    schema = copy.deepcopy(SCHEMAS["job_extract"])
    schema["title"] = "调用方自己的名字"
    for definition in schema.get("$defs", {}).values():
        definition.pop("description", None)
        definition.pop("title", None)
    result = run(build_gateway(), "job_extract", {}, schema=schema)
    JobContent.model_validate(dict(result.data))


def _example_score() -> dict:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    item = json.loads((root / "docs/examples/diagnosis-item.json").read_text(encoding="utf-8"))
    return item["score_result"]
