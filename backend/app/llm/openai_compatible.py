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
from typing import Any, Protocol

import httpx
import jsonschema

from app.contracts import ModelMetadata
from app.contracts.ports import StructuredResult, TaskContext

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

DEFAULT_SYSTEM_PROMPT = (
    "你是简历诊断系统的结构化数据处理器。只输出一个 JSON 对象，不要输出 Markdown 代码块或额外解释。"
)
# 06-ai-contract.md：报告输出预算 3,000 tokens。
REPORT_MAX_OUTPUT_TOKENS = 3000
# 格式修复时最多回显多少模型原文；只用于同一次调用，不落库。
REPAIR_ECHO_CHARS = 4000


class _ProviderUnavailable(Exception):
    """429/5xx/网络错误：可消耗一次重试预算。"""


class _Timeout(Exception):
    """单次调用超时：按契约不重试。"""


class _InvalidOutput(Exception):
    """供应商返回了无法解析的输出；携带可回显的内容用于一次格式修复。"""

    def __init__(self, content: str = ""):
        self.content = content


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


def _repair_messages(content: str) -> list[dict]:
    correction = (
        "上一次输出不是合法 JSON，或不符合给定的 JSON Schema。"
        "请只输出一个符合 Schema 的 JSON 对象；不要 Markdown 代码块，不要解释。"
    )
    messages: list[dict] = []
    if content:
        messages.append({"role": "assistant", "content": content[:REPAIR_ECHO_CHARS]})
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


def _decode(content: str, output_schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        raise GatewayError("MODEL_OUTPUT_INVALID", "模型输出不是合法 JSON") from None
    if not isinstance(data, dict):
        raise GatewayError("MODEL_OUTPUT_INVALID", "模型输出必须是 JSON 对象")
    try:
        jsonschema.validate(instance=data, schema=dict(output_schema))
    except jsonschema.ValidationError as error:
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", f"模型输出不符合 JSON Schema（{error.validator}）"
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
        _check_schema(output_schema)

        # 未知/停用/缺配置/能力不匹配的 model_id 在发出请求前失败，不静默回退。
        metadata = self.directory.resolve(context.model_id, task_name, self._clock())
        chars = count_input_chars(prompt_context)
        limit = INPUT_LIMITS[task_name]
        if chars > limit:
            raise GatewayError("INPUT_TOO_LONG", f"输入 {chars} 字超过 {limit} 上限，请缩减后重试")

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

        started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            try:
                content = await self._post(
                    _endpoint(connection.base_url), connection.api_key, body, timeout_seconds
                )
            except _Timeout:
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
            except _InvalidOutput as error:
                if attempts > RETRY_BUDGET:
                    self._record(
                        task_name, metadata, attempts, "MODEL_OUTPUT_INVALID", started, chars
                    )
                    raise GatewayError(
                        "MODEL_OUTPUT_INVALID", "供应商响应缺少可解析的 JSON 内容"
                    ) from None
                body = {**body, "messages": [*messages, *_repair_messages(error.content)]}
                await self._sleep(BACKOFF_SECONDS)
                continue
            except GatewayError:
                # 401/403/404 等配置类错误：不重试，也不静默换模型。
                self._record(task_name, metadata, attempts, "MODEL_UNAVAILABLE", started, chars)
                raise

            try:
                data = _decode(content, output_schema)
            except GatewayError:
                if attempts > RETRY_BUDGET:
                    self._record(
                        task_name, metadata, attempts, "MODEL_OUTPUT_INVALID", started, chars
                    )
                    raise
                # 非法 JSON 用一次格式修复；与 429/5xx 共用同一重试预算。
                body = {**body, "messages": [*messages, *_repair_messages(content)]}
                await self._sleep(BACKOFF_SECONDS)
                continue

            self._record(task_name, metadata, attempts, "ok", started, chars)
            return StructuredResult(
                data=data,
                model_metadata=metadata.model_copy(update={"generated_at": self._clock()}),
            )

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
