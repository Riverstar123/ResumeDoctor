"""Native strict calls and local guards, without contacting any provider."""

import asyncio
import json
from copy import deepcopy

import httpx
import jsonschema
import pytest

from app.contracts.ports import TaskContext
from app.llm import GatewayError, build_llm, task_output_schema
from app.llm.review import ReviewRequest
from app.llm.structured_output import (
    RESULT_TOOL,
    compact_schema,
    deepseek_strict_schema,
    output_parameters,
    strict_endpoint,
)
from tests.llm.test_real_gateway import CONTEXT, CUSTOM_SCHEMA, real_settings


def tool_result(data, **overrides):
    choice = {
        "finish_reason": "tool_calls",
        "message": {
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "id": "fixture-call",
                    "function": {
                        "name": RESULT_TOOL,
                        "arguments": json.dumps(data),
                    },
                }
            ],
        },
    }
    choice.update(overrides)
    return httpx.Response(
        200,
        json={
            "choices": [choice],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 60,
            },
        },
    )


def setup(responses):
    requests = []
    queue = list(responses)

    async def handler(request):
        requests.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    components = build_llm(
        real_settings(llm_model="deepseek-flash", llm_base_url="https://api.deepseek.com/v1"),
        transport=httpx.MockTransport(handler),
    )
    return components, requests


def run(components, schema=CUSTOM_SCHEMA):
    return asyncio.run(
        components.gateway.generate_structured(
            "profile_extract",
            {"prompt": "返回结构化JSON", "source_text": "合成资料"},
            schema,
            2,
            context=CONTEXT,
        )
    )


def test_official_deepseek_uses_forced_strict_tool_without_schema_in_prompt():
    components, requests = setup([tool_result({"ok": True})])
    assert run(components).data == {"ok": True}
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.deepseek.com/beta/chat/completions"
    assert "response_format" not in body
    assert body["thinking"] == {"type": "disabled"}
    function = body["tools"][0]["function"]
    assert function["strict"] is True
    assert function["parameters"] == CUSTOM_SCHEMA
    assert body["tool_choice"] == {"type": "function", "function": {"name": RESULT_TOOL}}
    assert '"properties"' not in body["messages"][1]["content"]
    assert '"source_text":"合成资料"' in body["messages"][1]["content"]
    assert requests[0].headers["Authorization"] == "Bearer test-secret-key"


@pytest.mark.parametrize(
    "task", ["profile_extract", "profile_chat", "job_extract", "diagnosis_report"]
)
def test_all_application_schemas_compile_without_mutating_authoritative_schema(task):
    schema = task_output_schema(task)
    before = deepcopy(schema)
    wire = deepseek_strict_schema(schema)
    jsonschema.Draft202012Validator.check_schema(wire)

    def walk(node):
        assert "$ref" not in node and "$defs" not in node
        assert not set(node) & {"minItems", "maxItems", "minLength", "maxLength", "uniqueItems"}
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for value in node["properties"].values():
                walk(value)
        if "items" in node:
            walk(node["items"])
        for value in node.get("anyOf", []):
            walk(value)

    walk(wire)
    assert schema == before


def test_documentation_compaction_preserves_business_fields_named_title_and_description():
    schema = {
        "type": "object",
        "title": "Annotation",
        "properties": {
            "title": {"type": "string", "minLength": 1, "title": "Label"},
            "description": {"type": "integer", "minimum": 2},
        },
    }
    compact = compact_schema(schema)
    assert "title" not in compact
    assert compact["properties"]["title"] == {"type": "string", "minLength": 1}
    assert compact["properties"]["description"] == {"type": "integer", "minimum": 2}


def test_native_report_schema_disallows_unconfirmed_templates_for_current_scoring():
    schema = task_output_schema("diagnosis_report")
    params = output_parameters(schema, True, {"suggestion_policy": "supported_facts_only"})
    wire = params["tools"][0]["function"]["parameters"]
    field = wire["properties"]["suggestions"]["items"]["properties"]["requires_user_input"]
    assert field == {"type": "boolean", "enum": [False]}
    assert "enum" not in schema["$defs"]["Suggestion"]["properties"]["requires_user_input"]


def test_local_length_constraints_remain_mandatory_in_strict_mode():
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    }
    components, requests = setup([tool_result({"text": ""})])
    with pytest.raises(GatewayError) as error:
        run(components, schema)
    assert error.value.reason_code == "SCHEMA_INVALID"
    assert len(requests) == 2
    assert all("tools" in json.loads(request.content) for request in requests)
    assert components.gateway.calls[0].prompt_tokens == 200
    assert components.gateway.calls[0].completion_tokens == 40


@pytest.mark.parametrize(
    "message",
    [
        {"content": '{"ok": true}'},
        {"tool_calls": []},
        {"tool_calls": [None]},
        {"tool_calls": [{"type": "function", "function": {"name": "other", "arguments": "{}"}}]},
        {"tool_calls": [{"type": "function", "function": None}]},
    ],
)
def test_strict_mode_does_not_silently_accept_content_or_foreign_calls(message):
    components, requests = setup([tool_result({}, message=message)])
    with pytest.raises(GatewayError):
        run(components)
    assert len(requests) == 2


def test_review_replaces_tool_schema_and_accumulates_actual_usage():
    review_schema = {
        "type": "object",
        "properties": {"approved": {"type": "boolean"}},
        "required": ["approved"],
        "additionalProperties": False,
    }
    components, requests = setup([tool_result({"ok": True}), tool_result({"approved": True})])
    result = asyncio.run(
        components.gateway.generate_reviewed(
            "diagnosis_report",
            {"prompt": "生成"},
            CUSTOM_SCHEMA,
            2,
            context=TaskContext("real-default"),
            validate_output=lambda data: None,
            build_review=lambda data: ReviewRequest(
                {"prompt": "审核"}, review_schema, lambda raw: None
            ),
        )
    )
    assert result.data == {"ok": True}
    schemas = [
        json.loads(request.content)["tools"][0]["function"]["parameters"] for request in requests
    ]
    assert schemas == [CUSTOM_SCHEMA, review_schema]
    call = components.gateway.calls[0]
    assert (call.prompt_tokens, call.completion_tokens, call.prompt_cache_hit_tokens) == (
        200,
        40,
        120,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com",
        "https://proxy.example/v1",
        "https://api.deepseek.com.evil.example",
        "https://api.deepseek.com/custom",
    ],
)
def test_strict_mode_never_redirects_keys_from_another_origin_or_path(url):
    with pytest.raises(GatewayError) as error:
        strict_endpoint(url)
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_truncated_tool_review_never_retries_when_the_tool_envelope_is_missing():
    components, requests = setup(
        [
            tool_result({"ok": True}),
            tool_result({}, finish_reason="length", message={}),
        ]
    )
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            components.gateway.generate_reviewed(
                "diagnosis_report",
                {"prompt": "生成"},
                CUSTOM_SCHEMA,
                2,
                context=CONTEXT,
                validate_output=lambda raw: None,
                build_review=lambda raw: ReviewRequest(
                    {"prompt": "审核"}, CUSTOM_SCHEMA, lambda raw: None
                ),
            )
        )
    assert error.value.reason_code == "OUTPUT_TRUNCATED"
    assert len(requests) == 2


def test_native_review_cannot_expand_the_quote_echo_budget():
    from app.reporting.grounding import GroundingReview

    schema = GroundingReview.model_json_schema()
    params = output_parameters(schema, True, {"review_prompt_version": "report-grounding-v7"})
    wire = params["tools"][0]["function"]["parameters"]
    assert wire["properties"]["evidence_checks"] == {"type": "null"}
    assert "anyOf" in schema["properties"]["evidence_checks"]


def test_non_object_provider_choice_is_a_bounded_output_failure():
    components, requests = setup([httpx.Response(200, json={"choices": [None]})])
    with pytest.raises(GatewayError) as error:
        run(components)
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert len(requests) == 2


def test_native_advice_is_assembled_and_reviewed_under_the_original_deadline(example):
    from app.contracts import DiagnosisItem, Job, Profile
    from app.reporting import ReportService
    from app.reporting.explanation import assemble_report
    from app.reporting.grounding import build_grounding_review
    from app.reporting.privacy import filter_report_context

    profile = Profile.model_validate(example("profile.json"))
    job = Job.model_validate(example("job.json"))
    item = DiagnosisItem.model_validate(example("diagnosis-item.json"))
    advice = {"suggestions": [], "actions": []}
    expected = assemble_report(advice, item.score_result)
    sent = filter_report_context(ReportService._prompt_context(profile, job, item.score_result))
    review = build_grounding_review(expected, sent)
    verdict = {
        "checks": [
            {"item_id": entry["item_id"], "verdict": "supported", "supports": []}
            for entry in review.prompt_context["items"]
        ],
        "evidence_checks": None,
    }
    components, requests = setup([tool_result(advice), tool_result(verdict)])
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-06T00:00:00Z"
    )
    report = asyncio.run(
        ReportService(components.gateway, privacy_filter=filter_report_context).generate_report(
            profile, job, item.score_result, metadata, context=CONTEXT
        )
    )
    assert report.model_dump(mode="json") == expected
    bodies = [json.loads(r.content) for r in requests]
    schemas = [b["tools"][0]["function"]["parameters"] for b in bodies]
    assert set(schemas[0]["properties"]) == {"suggestions", "actions"}
    assert schemas[1]["properties"]["evidence_checks"] == {"type": "null"}
    assert len(requests) == 2 and components.gateway.calls[0].attempts == 2
    assert components.gateway.calls[0].prompt_tokens == 200
