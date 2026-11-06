"""PR #76 review: a malformed review must never be replaced by a fresh approval."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.llm import GatewayError
from app.llm.review import ReviewRequest
from app.reporting.grounding import GroundingReview, _reject_explicit_verdicts
from tests.llm.test_real_gateway import CONTEXT, CUSTOM_SCHEMA
from tests.llm.test_real_gateway import ok as json_result
from tests.llm.test_reviewed_gateway import setup as json_setup
from tests.llm.test_structured_output import setup, tool_result


def verdict(state="supported"):
    return {
        "checks": [{"item_id": "summary", "verdict": state, "supports": [], "issues": []}],
        "evidence_checks": None,
    }


def review_request(_):
    def validate(raw):
        _reject_explicit_verdicts(raw)
        GroundingReview.model_validate(raw)

    return ReviewRequest(
        {"prompt": "Independent review", "review_prompt_version": "report-grounding-v8"},
        GroundingReview.model_json_schema(),
        validate,
        reject_if_declined=_reject_explicit_verdicts,
    )


def corrupt_review(fault):
    response = tool_result(verdict("unsupported" if fault == "extra_tool" else "supported"))
    value = response.json()
    message = value["choices"][0]["message"]
    if fault == "extra_tool":
        message["tool_calls"].append(deepcopy(message["tool_calls"][0]))
    elif fault == "invalid_json":
        message["tool_calls"][0]["function"]["arguments"] = '{"checks":[{"verdict":"unsupported"},'
    elif fault == "duplicate_verdict":
        message["tool_calls"][0]["function"]["arguments"] = json.dumps(verdict()).replace(
            '"verdict": "supported"', '"verdict":"unsupported","verdict":"supported"'
        )
    elif fault == "extra_choice":
        value["choices"].append(tool_result(verdict("unsupported")).json()["choices"][0])
    elif fault == "mixed_text":
        message["content"] = "unsupported"
    elif fault == "duplicate_envelope_key":
        return httpx.Response(
            200,
            content=json.dumps(value)
            .replace('"tool_calls": [', '"tool_calls": [], "tool_calls": [')
            .encode(),
        )
    return httpx.Response(200, json=value)


@pytest.mark.parametrize(
    "fault",
    [
        "extra_tool",
        "invalid_json",
        "duplicate_verdict",
        "extra_choice",
        "mixed_text",
        "duplicate_envelope_key",
    ],
)
def test_malformed_review_is_final_without_third_approval_request(fault):
    components, requests = setup(
        [tool_result({"ok": True}), corrupt_review(fault), tool_result(verdict())]
    )
    with pytest.raises(GatewayError):
        asyncio.run(
            components.gateway.generate_reviewed(
                "diagnosis_report",
                {"prompt": "Generate"},
                CUSTOM_SCHEMA,
                2,
                context=CONTEXT,
                validate_output=lambda raw: None,
                build_review=review_request,
            )
        )
    assert len(requests) == 2 and components.gateway.calls[0].attempts == 2
    assert components.gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


def test_offline_payload_decoder_rejects_duplicate_verdict():
    from app.tools.replay_report import payload

    with pytest.raises(GatewayError) as caught:
        payload(corrupt_review("duplicate_verdict").json())
    assert caught.value.reason_code == "JSON_INVALID"


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("fault", ["content_filter", "unknown_finish", "refusal", "legacy_call"])
def test_refusal_or_ambiguous_finish_is_terminal_for_both_response_modes(strict, fault):
    response = tool_result(verdict()).json() if strict else json_result(verdict()).json()
    choice = response["choices"][0]
    if fault in {"content_filter", "unknown_finish"}:
        choice["finish_reason"] = "content_filter" if fault == "content_filter" else "error"
    elif fault == "refusal":
        choice["message"]["refusal"] = "Synthetic refusal"
    else:
        choice["message"]["function_call"] = {"arguments": json.dumps(verdict("unsupported"))}
    failed = httpx.Response(200, json=response)
    if strict:
        components, requests = setup([tool_result({"ok": True}), failed, tool_result(verdict())])
        gateway = components.gateway
        call = gateway.generate_reviewed(
            "diagnosis_report",
            {"prompt": "Generate"},
            CUSTOM_SCHEMA,
            2,
            context=CONTEXT,
            validate_output=lambda raw: None,
            build_review=review_request,
        )
    else:
        call, gateway, requests = json_setup(
            [json_result({"ok": True}), failed, json_result(verdict())],
            build_review=review_request,
        )
    with pytest.raises(GatewayError):
        asyncio.run(call)
    assert len(requests) == 2 and gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


def test_json_mode_cannot_ignore_a_tool_with_a_conflicting_verdict():
    mixed = json_result(verdict()).json()
    mixed["choices"][0]["message"]["tool_calls"] = tool_result(verdict("unsupported")).json()[
        "choices"
    ][0]["message"]["tool_calls"]
    call, gateway, requests = json_setup(
        [json_result({"ok": True}), httpx.Response(200, json=mixed), json_result(verdict())],
        build_review=review_request,
    )
    with pytest.raises(GatewayError):
        asyncio.run(call)
    assert len(requests) == 2 and gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("choices", [[], [None], [{"message": None}]])
def test_offline_decoder_reports_malformed_choices_without_indexing_them(choices):
    from app.tools.replay_report import payload

    with pytest.raises(GatewayError):
        payload({"choices": choices})


def test_offline_json_mode_accepts_an_empty_tool_call_list_like_the_http_parser():
    from app.tools.replay_report import payload

    response = json_result({"ok": True}).json()
    response["choices"][0]["message"]["tool_calls"] = []
    assert payload(response) == {"ok": True}
