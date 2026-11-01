"""A model call has one deadline across HTTP, validation, repair and backoff."""

import asyncio
import time

import httpx
import pytest

from app.llm import GatewayError, OpenAICompatibleGateway, build_llm
from tests.llm.test_real_gateway import CONTEXT, CUSTOM_SCHEMA, ok, raw, real_settings


def reject_false(data):
    if not data["ok"]:
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "Synthetic rejection", reason_code="UNSUPPORTED_NUMBERS"
        )


@pytest.mark.parametrize("first", ["provider", "json", "schema", "semantic", "truncated"])
def test_backoff_cannot_outlive_the_shared_call_deadline(first):
    requests = []
    first_response = {
        "provider": httpx.Response(429),
        "json": raw("not json"),
        "schema": ok({"unexpected": True}),
        "semantic": ok({"ok": False}),
        "truncated": httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":'}, "finish_reason": "length"}]},
        ),
    }[first]

    async def handler(request):
        requests.append(request)
        return first_response if len(requests) == 1 else ok({"ok": True})

    async def slow_backoff(_):
        await asyncio.sleep(0.2)

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    gateway = OpenAICompatibleGateway(
        components.directory, transport=httpx.MockTransport(handler), sleep=slow_backoff
    )
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_validated(
                "diagnosis_report",
                {"prompt": "p"},
                CUSTOM_SCHEMA,
                0.1,
                context=CONTEXT,
                validate_output=reject_false,
            )
        )
    assert error.value.code == "MODEL_TIMEOUT"
    assert len(requests) == 1
    assert len(gateway.calls) == 1
    assert gateway.calls[0].attempts == 1
    assert gateway.calls[0].outcome == "MODEL_TIMEOUT"


@pytest.mark.parametrize("semantic", [False, True])
def test_retry_passes_only_the_remaining_budget_to_http(semantic):
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            await asyncio.sleep(0.02)
            return ok({"ok": False}) if semantic else raw("not json")
        return ok({"ok": True})

    async def no_backoff(_):
        pass

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    gateway = OpenAICompatibleGateway(
        components.directory, transport=httpx.MockTransport(handler), sleep=no_backoff
    )
    result = asyncio.run(
        gateway.generate_validated(
            "diagnosis_report",
            {"prompt": "p"},
            CUSTOM_SCHEMA,
            2,
            context=CONTEXT,
            validate_output=reject_false,
        )
    )
    assert result.data == {"ok": True}
    assert len(requests) == 2
    first, second = [r.extensions["timeout"]["read"] for r in requests]
    assert 0 < second < first <= 2
    assert gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "ok"


@pytest.mark.parametrize("invalid", [False, True])
def test_synchronous_validation_is_included_in_the_deadline(invalid):
    requests = []

    async def handler(request):
        requests.append(request)
        return ok({"ok": True})

    def validate(_):
        time.sleep(0.1)
        if invalid:
            raise GatewayError("MODEL_OUTPUT_INVALID", "Synthetic invalid output")

    async def no_backoff(_):
        pass

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    gateway = OpenAICompatibleGateway(
        components.directory, transport=httpx.MockTransport(handler), sleep=no_backoff
    )
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_validated(
                "diagnosis_report",
                {"prompt": "p"},
                CUSTOM_SCHEMA,
                0.05,
                context=CONTEXT,
                validate_output=validate,
            )
        )
    assert error.value.code == "MODEL_TIMEOUT"
    assert len(requests) == 1
    assert len(gateway.calls) == 1
    assert gateway.calls[0].outcome == "MODEL_TIMEOUT"


def test_caller_cancellation_is_not_reported_as_a_model_timeout():
    async def run():
        entered = asyncio.Event()

        async def handler(_):
            entered.set()
            await asyncio.sleep(10)
            return ok({"ok": True})

        components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
        task = asyncio.create_task(
            components.gateway.generate_structured(
                "profile_extract", {"prompt": "p"}, CUSTOM_SCHEMA, 5, context=CONTEXT
            )
        )
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert components.gateway.calls == []

    asyncio.run(run())
