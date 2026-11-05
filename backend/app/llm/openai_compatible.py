"""OpenAI-compatible Chat Completions 真实适配器（AI-02）。

只承诺兼容 Chat Completions 协议的端点：POST `{LLM_BASE_URL}/chat/completions`，
用 Bearer 凭证请求 `choices[0].message.content` 中的 JSON。其他协议（例如 Anthropic
Messages API）需要新增独立适配器，不能只改 URL。

行为与 `FakeModelGateway` 对齐：单次调用 45 秒截止；429/5xx 与非法/不符 Schema
的输出共用**一次**重试预算（短退避）；超时不重试；输入超限在发出请求前失败。
供应商 401/403/404 等配置类错误不重试，映射为 `MODEL_UNAVAILABLE`。

安全：密钥只进入 Authorization 头；不写日志、不进异常消息、不进入公开模型 DTO。
调用记录只保留 task_name、model_id、提示版本、尝试次数、结果、耗时和输入字符数。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from typing import Any, Protocol

import httpx
import jsonschema

from app.contracts import ModelMetadata
from app.contracts.ports import StructuredResult, TaskContext
from app.diagnostics import REPAIR_HINTS

from .config import ModelConnection
from .errors import GatewayError
from .gateway import (
    BACKOFF_SECONDS,
    INPUT_LIMITS,
    RETRY_BUDGET,
    GatewayCall,
    append_call,
    count_input_chars,
    utc_now,
)
from .review import ReviewRejected, ReviewRequest

DEFAULT_SYSTEM_PROMPT = (
    "你是简历诊断系统的结构化数据处理器。只输出一个 JSON 对象，不要输出 Markdown 代码块或额外解释。"
)
# 06-ai-contract.md：报告输出预算 3,000 tokens。
REPORT_MAX_OUTPUT_TOKENS = 6000
# 格式修复时最多回显多少模型原文；只用于同一次调用，不落库。
REPAIR_ECHO_CHARS = 4000


class _ProviderUnavailable(Exception):
    """429/5xx/网络错误：可消耗一次重试预算。"""


class _Timeout(Exception):
    """单次调用超时：按契约不重试。"""


class _InvalidOutput(Exception):
    """供应商返回了无法解析的输出；携带可回显的内容用于一次格式修复。"""

    def __init__(self, content: str = "", reason_code: str = "JSON_INVALID"):
        self.content = content
        self.reason_code = reason_code


class GatewayDirectory(Protocol):
    def resolve(self, model_id: str, capability: str, now: str) -> ModelMetadata: ...

    def connection(self, model_id: str) -> ModelConnection: ...


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _messages(prompt_context: Mapping[str, Any], output_schema: Mapping[str, Any]) -> list[dict]:
    prompt = prompt_context.get("prompt")
    system = prompt.strip() if isinstance(prompt, str) and prompt.strip() else DEFAULT_SYSTEM_PROMPT
    data = {key: value for key, value in prompt_context.items() if key != "prompt"}
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        schema = json.dumps(output_schema, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "调用方提供的 prompt_context 不能序列化为 JSON"
        ) from None
    user = (
        "任务数据（JSON）：\n"
        f"{payload}\n\n"
        "输出必须满足以下 JSON Schema，且只输出一个 JSON 对象；"
        "不要 Markdown 代码块，不要解释：\n"
        f"{schema}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _repair_messages(
    content: str, remaining: int, reason_code: str | None = None
) -> list[dict] | None:
    """在剩余输入预算内构造格式修复消息。

    修复请求会额外携带模型回显与修复指令，这些文本同样计入单次输入上限。
    回显最多使用 `REPAIR_ECHO_CHARS`，并进一步收窄到剩余预算；连修复指令
    都放不下时返回 `None`，由调用方安全结束，不发送超预算请求，也不截断
    原始输入证据。
    """
    correction = (
        "上一次输出不是合法 JSON，或不符合给定的 JSON Schema。"
        "请只输出一个符合 Schema 的 JSON 对象；不要 Markdown 代码块，不要解释。"
    )
    if isinstance(reason_code, str) and reason_code in REPAIR_HINTS:
        correction = (
            "上一次 JSON 内容未通过校验。"
            + REPAIR_HINTS[reason_code]
            + "同时复核：gap 引用必须是对应评分证据的子集；revised 中的数字只能来自该条引用。"
            "JD 门槛和未来计划放在 rationale/actions，不要写进 revised。"
            + "只输出符合 Schema 的完整 JSON，不要解释。"
        )
    allowance = remaining - len(correction)
    if allowance < 0:
        return None
    messages: list[dict] = []
    echo = content[: min(REPAIR_ECHO_CHARS, allowance)]
    if echo:
        messages.append({"role": "assistant", "content": echo})
    messages.append({"role": "user", "content": correction})
    return messages


def _check_schema(output_schema: Mapping[str, Any]) -> None:
    try:
        validator = jsonschema.validators.validator_for(dict(output_schema))
        validator.check_schema(dict(output_schema))
    except jsonschema.SchemaError:
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "调用方提供的 output_schema 不是合法 JSON Schema"
        ) from None


def _decode(
    content: str,
    output_schema: Mapping[str, Any],
    reject_if_declined: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "模型输出不是合法 JSON", reason_code="JSON_INVALID"
        ) from None
    if not isinstance(data, dict):
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "模型输出必须是 JSON 对象", reason_code="SCHEMA_INVALID"
        )
    if reject_if_declined is not None:
        # A negative review plus a schema defect must not be "repaired" into approval.
        reject_if_declined(data)
    try:
        jsonschema.validate(instance=data, schema=dict(output_schema))
    except jsonschema.ValidationError as error:
        raise GatewayError(
            "MODEL_OUTPUT_INVALID",
            f"模型输出不符合 JSON Schema（{error.validator}）",
            reason_code="SCHEMA_INVALID",
        ) from None
    return data


class OpenAICompatibleGateway:
    """通过 Chat Completions HTTP 接口调用目录中的真实模型。"""

    is_fake = False

    def __init__(
        self,
        directory: GatewayDirectory,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], str] | None = None,
    ):
        self.directory = directory
        self._transport = transport
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or utc_now
        self.calls: list[GatewayCall] = []

    async def generate_structured(
        self, task_name, prompt_context, output_schema, timeout_seconds, *, context
    ) -> StructuredResult:
        return await self._generate(
            task_name, prompt_context, output_schema, timeout_seconds, context=context
        )

    async def generate_validated(
        self,
        task_name,
        prompt_context,
        output_schema,
        timeout_seconds,
        *,
        context,
        validate_output: Callable[[Mapping[str, Any]], None],
    ) -> StructuredResult:
        """Optional report capability; semantic repair shares the original retry budget."""
        return await self._generate(
            task_name,
            prompt_context,
            output_schema,
            timeout_seconds,
            context=context,
            validate_output=validate_output,
        )

    async def generate_reviewed(
        self,
        task_name,
        prompt_context,
        output_schema,
        timeout_seconds,
        *,
        context,
        validate_output: Callable[[Mapping[str, Any]], None],
        build_review: Callable[[Mapping[str, Any]], ReviewRequest],
    ) -> StructuredResult:
        """Two mandatory phases, one deadline and one shared failure retry.

        A normal call uses two HTTP requests; generation/transport/review-format
        failures share one retry, so at most three requests are sent. A substantive
        review rejection never retries. The reviewer cannot replace the candidate.
        """
        return await self._generate(
            task_name,
            prompt_context,
            output_schema,
            timeout_seconds,
            context=context,
            validate_output=validate_output,
            build_review=build_review,
        )

    async def _generate(
        self,
        task_name: str,
        prompt_context: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        timeout_seconds: float,
        *,
        context: TaskContext,
        validate_output: Callable[[Mapping[str, Any]], None] | None = None,
        build_review: Callable[[Mapping[str, Any]], ReviewRequest] | None = None,
    ) -> StructuredResult:
        started = time.monotonic()
        if not isinstance(output_schema, Mapping):
            raise GatewayError("MODEL_OUTPUT_INVALID", "output_schema 必须是 JSON Schema 映射")
        _check_schema(output_schema)

        # 未知/停用/缺配置/能力不匹配的 model_id 在发出请求前失败，不静默回退。
        metadata = self.directory.resolve(context.model_id, task_name, self._clock())
        chars = count_input_chars(prompt_context)
        limit = INPUT_LIMITS[task_name]
        if chars > limit:
            raise GatewayError("INPUT_TOO_LONG", f"输入 {chars} 字超过 {limit} 上限，请缩减后重试")
        # 修复重试额外携带的回显与指令也只能使用剩余预算。
        repair_budget = limit - chars

        connection = self.directory.connection(context.model_id)
        messages = _messages(prompt_context, output_schema)
        body: dict[str, Any] = {
            "model": connection.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if task_name == "diagnosis_report":
            body["max_tokens"] = REPORT_MAX_OUTPUT_TOKENS
        if connection.reasoning_effort is not None:
            body["reasoning_effort"] = connection.reasoning_effort

        deadline = started + timeout_seconds
        attempts = 0
        retries = 0
        review_pending = build_review is not None
        candidate: dict[str, Any] | None = None
        phase_schema = output_schema
        phase_validator = validate_output
        decline_guard = None

        def remaining_time() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return remaining

        try:
            # HTTP、退避和修复共用整次调用的截止时间；同步校验后也检查剩余预算。
            async with asyncio.timeout(remaining_time()):
                while True:
                    remaining = remaining_time()
                    attempts += 1
                    try:
                        content = await self._post(
                            _endpoint(connection.base_url), connection.api_key, body, remaining
                        )
                    except _ProviderUnavailable:
                        if retries >= RETRY_BUDGET:
                            raise GatewayError(
                                "PROVIDER_UNAVAILABLE", "模型供应商暂时不可用"
                            ) from None
                        retries += 1
                        await self._sleep(BACKOFF_SECONDS)
                        continue
                    except _InvalidOutput as error:
                        if candidate is not None and error.reason_code == "OUTPUT_TRUNCATED":
                            # A truncated review may already contain a negative
                            # verdict. Never discard it and ask for fresh approval.
                            raise GatewayError(
                                "MODEL_OUTPUT_INVALID",
                                "事实核对输出被截断，已保留规则评分。",
                                reason_code="OUTPUT_TRUNCATED",
                            ) from None
                        if retries >= RETRY_BUDGET:
                            raise GatewayError(
                                "MODEL_OUTPUT_INVALID",
                                "供应商响应缺少可解析的 JSON 内容",
                                reason_code=error.reason_code,
                            ) from None
                        repair = _repair_messages(error.content, repair_budget, error.reason_code)
                        if repair is None:
                            raise GatewayError(
                                "MODEL_OUTPUT_INVALID",
                                "模型输出不可解析，且输入已无剩余预算追加格式修复；请缩减输入后重试",
                                reason_code=error.reason_code,
                            ) from None
                        body = {**body, "messages": [*messages, *repair]}
                        retries += 1
                        await self._sleep(BACKOFF_SECONDS)
                        continue

                    try:
                        data = _decode(content, phase_schema, decline_guard)
                        if phase_validator is not None:
                            phase_validator(data)
                    except ReviewRejected:
                        # Never ask the same reviewer again just to obtain approval.
                        raise
                    except GatewayError as error:
                        if retries >= RETRY_BUDGET:
                            raise
                        # 格式与语义修复仍和网络失败共用一次重试预算。
                        repair = _repair_messages(content, repair_budget, error.reason_code)
                        if repair is None:
                            raise GatewayError(
                                "MODEL_OUTPUT_INVALID",
                                "模型输出未通过校验，且输入已无剩余预算追加格式修复；请缩减输入后重试",
                                reason_code=error.reason_code,
                            ) from None
                        body = {**body, "messages": [*messages, *repair]}
                        retries += 1
                        await self._sleep(BACKOFF_SECONDS)
                        continue

                    remaining_time()
                    if review_pending:
                        candidate = deepcopy(data)
                        review = build_review(deepcopy(candidate))
                        _check_schema(review.output_schema)
                        review_chars = count_input_chars(review.prompt_context)
                        if review_chars > limit:
                            raise GatewayError(
                                "MODEL_OUTPUT_INVALID",
                                "报告事实核对超过输入预算，已保留规则评分。",
                                reason_code="REPORT_VALIDATION_FAILED",
                            )
                        phase_schema = review.output_schema
                        phase_validator = review.validate_output
                        decline_guard = review.reject_if_declined
                        messages = _messages(review.prompt_context, phase_schema)
                        body = {**body, "messages": messages}
                        repair_budget = limit - review_chars
                        chars += review_chars
                        review_pending = False
                        remaining_time()
                        continue

                    result = StructuredResult(
                        data=candidate if candidate is not None else data,
                        model_metadata=metadata.model_copy(update={"generated_at": self._clock()}),
                    )
                    remaining_time()
                    break
        except (TimeoutError, _Timeout):
            failure = GatewayError("MODEL_TIMEOUT", "模型调用超过总时限")
        except GatewayError as error:
            failure = (
                GatewayError("MODEL_TIMEOUT", "模型调用超过总时限")
                if time.monotonic() >= deadline
                else error
            )
        else:
            self._record(task_name, metadata, attempts, "ok", started, chars)
            return result
        self._record(task_name, metadata, attempts, failure.code, started, chars)
        raise failure from None

    async def _post(
        self,
        url: str,
        api_key: str,
        body: Mapping[str, Any],
        timeout_seconds: float,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await asyncio.wait_for(
                    client.post(url, headers=headers, json=dict(body)), timeout_seconds
                )
        except (TimeoutError, httpx.TimeoutException):
            raise _Timeout from None
        except httpx.InvalidURL:
            # 配置阶段已校验；若仍出现（例如自定义目录绕过工厂），映射为安全配置错误。
            raise GatewayError(
                "MODEL_UNAVAILABLE", "LLM_BASE_URL 不是可用的 HTTP 地址；请检查模型配置"
            ) from None
        except httpx.HTTPError:
            raise _ProviderUnavailable from None

        status = response.status_code
        if status == 429 or 500 <= status <= 599:
            raise _ProviderUnavailable
        if status != 200:
            raise GatewayError(
                "MODEL_UNAVAILABLE",
                f"供应商返回 HTTP {status}；请检查 LLM_BASE_URL、模型名与密钥配置",
            )
        try:
            payload = response.json()
        except ValueError:
            raise _InvalidOutput from None
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _InvalidOutput from None
        if payload["choices"][0].get("finish_reason") == "length":
            raise _InvalidOutput(
                content if isinstance(content, str) else "", reason_code="OUTPUT_TRUNCATED"
            )
        if not isinstance(content, str) or not content.strip():
            raise _InvalidOutput(content if isinstance(content, str) else "")
        return content.strip()

    def _record(
        self,
        task_name: str,
        metadata: ModelMetadata,
        attempts: int,
        outcome: str,
        started: float,
        input_chars: int,
    ) -> None:
        append_call(self.calls, task_name, metadata, attempts, outcome, started, input_chars)
