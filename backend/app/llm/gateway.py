"""M5 统一模型网关：四类任务的单一入口、结构化输出校验与失败替身。

对应 [06-ai-contract.md](../../../docs/06-ai-contract.md) 的失败、预算与降级：
单次调用超时即 MODEL_TIMEOUT；供应商 429/5xx 与非法 JSON 各消耗一次共用重试
预算（最多 1 次，短退避）；输入超限直接 INPUT_TOO_LONG，不静默截断。

`output_schema` 按端口签名接收并校验为映射。AI-01 的 fake 结果按冻结契约 DTO
校验（与 M2 `port_dto` 同一模式）；真实适配器按任意 JSON Schema 校验由 AI-02 交付。
失败行为只来自服务端注入的 `failures`，绝不从用户输入或模型输出读取。
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.contracts import JobContent, ModelMetadata, ProfileContent, ReportContent
from app.contracts.ports import StructuredResult, TaskContext

from .catalog import ModelDirectory
from .errors import GatewayError
from .synthetic import (
    synthetic_chat_payload,
    synthetic_job_payload,
    synthetic_profile_payload,
    synthetic_report_payload,
)

# 最多一次重试：供应商不可用与非法 JSON 共用同一预算。
RETRY_BUDGET = 1
BACKOFF_SECONDS = 0.1
DEFAULT_TIMEOUT_SECONDS = 45.0
# 单次输入上限（字符）：报告 20,000，提取 30,000。超出请用户缩减。
INPUT_LIMITS = {
    "profile_extract": 30_000,
    "profile_chat": 30_000,
    "job_extract": 30_000,
    "diagnosis_report": 20_000,
}
# timeout 替身用真实 asyncio 睡眠，交由外层 wait_for 取消；不经过注入的 sleep。
_HANG_SECONDS = 3600.0

Behavior = Literal["ok", "timeout", "invalid_json", "provider_unavailable"]
BEHAVIORS: frozenset[str] = frozenset({"ok", "timeout", "invalid_json", "provider_unavailable"})

# profile_chat 的输出是「助手消息 + 档案草稿」的组合，在 _validate 中单独处理。
_OUTPUT_DTOS: dict[str, type[BaseModel]] = {
    "profile_extract": ProfileContent,
    "job_extract": JobContent,
    "diagnosis_report": ReportContent,
}


class _ProviderUnavailable(Exception):
    """内部哨兵：模拟 429/5xx，不进 API 表面。"""


@dataclass(frozen=True)
class GatewayCall:
    """不含原文与密钥的调用记录，供日志与失败排查。"""

    task_name: str
    model_id: str
    prompt_version: str
    attempts: int
    outcome: str
    duration_ms: int
    input_chars: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _input_chars(value: Any) -> int:
    """统计输入文本字符数；只累加字符串值，忽略键名与结构符号。"""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, Mapping):
        return sum(_input_chars(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_input_chars(item) for item in value)
    return 0


class FakeModelGateway:
    """可独立调用的假网关，供 C/B 在没有真实模型与密钥时开发。

    `failures` 是服务端注入的失败替身（task_name → 行为），值为
    `timeout` / `invalid_json` / `provider_unavailable`；用户经历或 JD 文本
    不会触发这些开关。
    """

    is_fake = True

    def __init__(
        self,
        directory: ModelDirectory,
        *,
        failures: Mapping[str, str] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], str] | None = None,
    ):
        self.directory = directory
        self.failures = dict(failures or {})
        unknown = set(self.failures.values()) - BEHAVIORS
        if unknown:
            raise ValueError(f"未知的失败替身行为：{sorted(unknown)}")
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or _utc_now
        self.calls: list[GatewayCall] = []

    async def generate_structured(
        self,
        task_name: str,
        prompt_context: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        timeout_seconds: float,
        *,
        context: TaskContext,
    ) -> StructuredResult:
        if not isinstance(output_schema, Mapping):
            raise GatewayError("MODEL_OUTPUT_INVALID", "output_schema 必须是 JSON Schema 映射")
        # 未知/停用/能力不匹配的 model_id 在此明确失败，不静默回退其他供应商。
        metadata = self.directory.resolve(context.model_id, task_name, self._clock())

        chars = _input_chars(prompt_context)
        limit = INPUT_LIMITS[task_name]
        if chars > limit:
            raise GatewayError("INPUT_TOO_LONG", f"输入 {chars} 字超过 {limit} 上限，请缩减后重试")

        started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            behavior = self.failures.get(task_name, "ok")
            try:
                raw = await asyncio.wait_for(
                    self._produce(task_name, prompt_context, behavior), timeout_seconds
                )
            except TimeoutError:
                self._record(task_name, metadata, attempts, "MODEL_TIMEOUT", started, chars)
                raise GatewayError("MODEL_TIMEOUT", "模型调用超过单次时限") from None
            except _ProviderUnavailable:
                if attempts > RETRY_BUDGET:
                    self._record(
                        task_name, metadata, attempts, "PROVIDER_UNAVAILABLE", started, chars
                    )
                    raise GatewayError("PROVIDER_UNAVAILABLE", "模型供应商暂时不可用") from None
                await self._sleep(BACKOFF_SECONDS)
                continue

            try:
                data = self._validate(task_name, raw)
            except GatewayError:
                if attempts > RETRY_BUDGET:
                    self._record(
                        task_name, metadata, attempts, "MODEL_OUTPUT_INVALID", started, chars
                    )
                    raise
                # 非法 JSON 用一次格式修复；共用同一重试预算。
                await self._sleep(BACKOFF_SECONDS)
                continue

            self._record(task_name, metadata, attempts, "ok", started, chars)
            return StructuredResult(
                data=data,
                model_metadata=metadata.model_copy(update={"generated_at": self._clock()}),
            )

    async def _produce(
        self, task_name: str, prompt_context: Mapping[str, Any], behavior: str
    ) -> Any:
        if behavior == "provider_unavailable":
            raise _ProviderUnavailable()
        if behavior == "timeout":
            await asyncio.sleep(_HANG_SECONDS)  # 由外层 wait_for 取消
        if behavior == "invalid_json":
            return "{ 这不是合法的 JSON"
        if task_name == "diagnosis_report":
            score = prompt_context.get("score_result")
            return synthetic_report_payload(score if isinstance(score, Mapping) else None)
        if task_name == "profile_chat":
            return synthetic_chat_payload()
        if task_name == "profile_extract":
            return synthetic_profile_payload()
        return synthetic_job_payload()

    def _validate(self, task_name: str, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise GatewayError("MODEL_OUTPUT_INVALID", "模型输出不是结构化对象")
        if task_name == "profile_chat":
            message = raw.get("assistant_message")
            if not isinstance(message, str) or not message:
                raise GatewayError("MODEL_OUTPUT_INVALID", "profile_chat 缺少 assistant_message")
            return {
                "assistant_message": message,
                "profile_content": self._validate_dto(ProfileContent, raw.get("profile_content")),
            }
        return self._validate_dto(_OUTPUT_DTOS[task_name], raw)

    @staticmethod
    def _validate_dto(model: type[BaseModel], value: Any) -> dict[str, Any]:
        try:
            return model.model_validate(value).model_dump(mode="json")
        except (ValidationError, ValueError, TypeError):
            raise GatewayError(
                "MODEL_OUTPUT_INVALID", f"模型输出不符合 {model.__name__} 结构"
            ) from None

    def _record(
        self,
        task_name: str,
        metadata: ModelMetadata,
        attempts: int,
        outcome: str,
        started: float,
        input_chars: int,
    ) -> None:
        # 只保留可排障的元信息，不记录原文、密钥或供应商回显。
        self.calls.append(
            GatewayCall(
                task_name=task_name,
                model_id=metadata.model_id,
                prompt_version=metadata.prompt_version,
                attempts=attempts,
                outcome=outcome,
                duration_ms=int((time.monotonic() - started) * 1000),
                input_chars=input_chars,
            )
        )
