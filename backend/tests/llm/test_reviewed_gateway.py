"""Two required HTTP stages share one deadline and one failure retry."""

import asyncio
import json
import time

import httpx
import pytest

from app.llm import GatewayError, build_llm
from app.llm.review import ReviewRejected, ReviewRequest
from tests.llm.test_real_gateway import CONTEXT, CUSTOM_SCHEMA, ok, raw, real_settings


def validate_candidate(data):
    if not data["ok"]:
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "Synthetic invalid draft", reason_code="UNSUPPORTED_NUMBERS"
        )


def validate_review(data):
    if not data["ok"]:
        raise ReviewRejected()


def review_for(candidate):
    return ReviewRequest(
        prompt_context={"prompt": "Independent review", "candidate": candidate},
        output_schema=CUSTOM_SCHEMA,
        validate_output=validate_review,
    )


def setup(responses, *, build_review=review_for, timeout=2):
    requests = []
    queue = list(responses)

    async def handler(request):
        requests.append(request)
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        return response

    async def no_sleep(_):
        pass

    gateway = build_llm(real_settings(), transport=httpx.MockTransport(handler)).gateway
    gateway._sleep = no_sleep
    call = gateway.generate_reviewed(
        "diagnosis_report",
        {"prompt": "Generate"},
        CUSTOM_SCHEMA,
        timeout,
        context=CONTEXT,
        validate_output=validate_candidate,
        build_review=build_review,
    )
    return call, gateway, requests


def test_two_requests_are_required_and_the_original_candidate_is_returned():
    call, gateway, requests = setup([ok({"ok": True}), ok({"ok": True})])
    assert asyncio.run(call).data == {"ok": True}
    assert len(requests) == 2
    assert len(gateway.calls) == 1 and gateway.calls[0].attempts == 2
    assert [json.loads(r.content)["messages"][0]["content"] for r in requests] == [
        "Generate",
        "Independent review",
    ]


@pytest.mark.parametrize(
    "failure", [httpx.Response(429), raw("not json"), ok({"unexpected": True}), ok({"ok": False})]
)
def test_generation_retry_and_mandatory_review_use_at_most_three_requests(failure):
    call, gateway, requests = setup([failure, ok({"ok": True}), ok({"ok": True})])
    assert asyncio.run(call).data == {"ok": True}
    assert len(requests) == 3 and gateway.calls[0].attempts == 3
    assert gateway.calls[0].outcome == "ok"


@pytest.mark.parametrize(
    "failure", [httpx.Response(500), raw("not json"), ok({"unexpected": True})]
)
def test_review_transport_or_format_can_use_the_one_remaining_retry(failure):
    call, gateway, requests = setup([ok({"ok": True}), failure, ok({"ok": True})])
    assert asyncio.run(call).data == {"ok": True}
    assert len(requests) == 3 and gateway.calls[0].attempts == 3
    assert all(
        json.loads(r.content)["messages"][0]["content"] == "Independent review"
        for r in requests[1:]
    )


@pytest.mark.parametrize(
    "failure", [httpx.Response(500), raw("not json"), ok({"unexpected": True})]
)
def test_review_has_no_separate_retry_after_generation_used_it(failure):
    call, gateway, requests = setup([httpx.Response(429), ok({"ok": True}), failure])
    with pytest.raises(GatewayError):
        asyncio.run(call)
    assert len(requests) == 3 and gateway.calls[0].attempts == 3
    assert gateway.calls[0].outcome != "ok"


def test_negative_review_is_final_even_when_retry_budget_remains():
    call, gateway, requests = setup([ok({"ok": True}), ok({"ok": False}), ok({"ok": True})])
    with pytest.raises(ReviewRejected):
        asyncio.run(call)
    assert len(requests) == 2 and gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("content", ['{"ok": false}', '{"ok": false,', '{"ok": true}'])
def test_truncated_review_never_reasks_even_when_its_json_is_parseable(content):
    truncated = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "length",
                }
            ]
        },
    )
    call, gateway, requests = setup([ok({"ok": True}), truncated, ok({"ok": True})])
    with pytest.raises(GatewayError) as error:
        asyncio.run(call)
    assert error.value.reason_code == "OUTPUT_TRUNCATED"
    assert len(requests) == 2 and gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


def test_generation_truncation_can_still_use_shared_retry_before_required_review():
    truncated = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": '{"ok":'},
                    "finish_reason": "length",
                }
            ]
        },
    )
    call, gateway, requests = setup([truncated, ok({"ok": True}), ok({"ok": True})])
    assert asyncio.run(call).data == {"ok": True}
    assert len(requests) == 3 and gateway.calls[0].attempts == 3


def test_review_cannot_mutate_the_saved_candidate():
    def build_review(candidate):
        candidate["ok"] = False
        return review_for(candidate)

    call, _, _ = setup([ok({"ok": True}), ok({"ok": True})], build_review=build_review)
    assert asyncio.run(call).data == {"ok": True}


def test_oversized_review_fails_without_sending_a_second_request():
    def build_review(candidate):
        return ReviewRequest({"data": "x" * 20_001}, CUSTOM_SCHEMA, validate_review)

    call, gateway, requests = setup([ok({"ok": True})], build_review=build_review)
    with pytest.raises(GatewayError) as error:
        asyncio.run(call)
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert len(requests) == 1 and gateway.calls[0].attempts == 1


def test_generation_and_review_share_remaining_http_timeout():
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            await asyncio.sleep(0.02)
        return ok({"ok": True})

    gateway = build_llm(real_settings(), transport=httpx.MockTransport(handler)).gateway
    asyncio.run(
        gateway.generate_reviewed(
            "diagnosis_report",
            {},
            CUSTOM_SCHEMA,
            1,
            context=CONTEXT,
            validate_output=validate_candidate,
            build_review=review_for,
        )
    )
    first, second = [r.extensions["timeout"]["read"] for r in requests]
    assert 0 < second < first <= 1
    assert gateway.calls[0].attempts == 2


@pytest.mark.parametrize("expire_in", ["review_http", "review_validation", "review_builder"])
def test_review_cannot_reset_or_outlive_the_shared_deadline(expire_in):
    requests = []

    async def handler(request):
        requests.append(request)
        if expire_in == "review_http" and len(requests) == 2:
            await asyncio.sleep(0.2)
        return ok({"ok": True})

    def slow_validate(data):
        time.sleep(0.1)
        validate_review(data)

    def build_review(candidate):
        if expire_in == "review_builder":
            time.sleep(0.1)
        return ReviewRequest(
            {"prompt": "Review"},
            CUSTOM_SCHEMA,
            slow_validate if expire_in == "review_validation" else validate_review,
        )

    gateway = build_llm(real_settings(), transport=httpx.MockTransport(handler)).gateway
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_reviewed(
                "diagnosis_report",
                {},
                CUSTOM_SCHEMA,
                0.05,
                context=CONTEXT,
                validate_output=validate_candidate,
                build_review=build_review,
            )
        )
    assert error.value.code == "MODEL_TIMEOUT"
    assert len(requests) == (1 if expire_in == "review_builder" else 2)
    assert len(gateway.calls) == 1 and gateway.calls[0].outcome == "MODEL_TIMEOUT"


def test_cancellation_during_review_still_propagates():
    async def run():
        reviewing = asyncio.Event()
        requests = []

        async def handler(request):
            requests.append(request)
            if len(requests) == 2:
                reviewing.set()
                await asyncio.sleep(10)
            return ok({"ok": True})

        gateway = build_llm(real_settings(), transport=httpx.MockTransport(handler)).gateway
        task = asyncio.create_task(
            gateway.generate_reviewed(
                "diagnosis_report",
                {},
                CUSTOM_SCHEMA,
                2,
                context=CONTEXT,
                validate_output=validate_candidate,
                build_review=review_for,
            )
        )
        await asyncio.wait_for(reviewing.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gateway.calls == []

    asyncio.run(run())
