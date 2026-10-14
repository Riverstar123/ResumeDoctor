"""失败替身：超时、非法 JSON、供应商不可用与重试预算（T11 的 fake 场景）。

失败只来自服务端注入的 `failures`；用户输入不会触发开关。供应商不可用与非法
JSON 各消耗一次共用的重试预算（最多 1 次重试），超时不重试。
"""

import asyncio

import pytest

from app.contracts import ProfileContent
from app.contracts.ports import TaskContext
from app.llm import (
    RETRY_BUDGET,
    FakeModelDirectory,
    FakeModelGateway,
    GatewayError,
    task_output_schema,
)

CONTEXT = TaskContext(model_id="demo-model-a")


class SleepCounter:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def build_gateway(failures: dict[str, str], sleep=None) -> FakeModelGateway:
    return FakeModelGateway(
        FakeModelDirectory(),
        failures=failures,
        sleep=sleep or SleepCounter(),
        clock=lambda: "2026-10-14T00:00:00Z",
    )


def test_retry_budget_is_exactly_one():
    assert RETRY_BUDGET == 1


def test_provider_unavailable_retries_once_then_fails():
    sleep = SleepCounter()
    gateway = build_gateway({"profile_extract": "provider_unavailable"}, sleep)
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_structured(
                "profile_extract", {}, task_output_schema("profile_extract"), 1.0, context=CONTEXT
            )
        )
    assert error.value.code == "PROVIDER_UNAVAILABLE"
    assert len(sleep.calls) == RETRY_BUDGET  # 短退避，共用一次预算
    assert [call.attempts for call in gateway.calls] == [RETRY_BUDGET + 1]
    assert gateway.calls[0].outcome == "PROVIDER_UNAVAILABLE"


def test_invalid_json_gets_one_format_repair_then_fails():
    sleep = SleepCounter()
    gateway = build_gateway({"job_extract": "invalid_json"}, sleep)
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_structured(
                "job_extract", {}, task_output_schema("job_extract"), 1.0, context=CONTEXT
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert len(sleep.calls) == RETRY_BUDGET
    assert [call.attempts for call in gateway.calls] == [RETRY_BUDGET + 1]
    assert gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


def test_timeout_is_not_retried():
    gateway = build_gateway({"profile_chat": "timeout"})
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            gateway.generate_structured(
                "profile_chat", {}, task_output_schema("profile_chat"), 0.01, context=CONTEXT
            )
        )
    assert error.value.code == "MODEL_TIMEOUT"
    assert [call.attempts for call in gateway.calls] == [1]
    assert gateway.calls[0].outcome == "MODEL_TIMEOUT"


def test_failures_are_scoped_to_their_task_name():
    gateway = build_gateway({"job_extract": "provider_unavailable"})
    result = asyncio.run(
        gateway.generate_structured(
            "profile_extract", {}, task_output_schema("profile_extract"), 1.0, context=CONTEXT
        )
    )
    ProfileContent.model_validate(dict(result.data))


def test_unknown_failure_behaviour_is_rejected_at_construction():
    with pytest.raises(ValueError):
        FakeModelGateway(FakeModelDirectory(), failures={"profile_extract": "explode"})
