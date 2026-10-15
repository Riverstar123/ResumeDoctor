"""通过 M5 统一网关调用模型的 IntakePort 实现。

职责边界：本模块只负责「组织提示词与数据 → 调用网关 → 用 M3 校验验证结果」。
超时、重试预算、输入长度上限、输出结构与 `model_id` 解析都由网关负责
（见 app/llm/gateway.py），这里不重复实现，也不吞掉 GatewayError——
错误码原样上抛，交给 M2 统一映射 HTTP。

来源编号（`source_id`）：每条证据都要标注它出自哪份文件或哪条消息，但
`IntakePort.build_profile` 的签名没有来源编号参数，M3 也无从得知 M2 生成的
document_id / message_id。因此这里用构造参数 `source_id` 承载该约定，默认取本模块
合成素材的编号，使接 M5 假网关时开箱可用；**M2 集成时应显式传入真实来源编号**。
该缺口已在 Issue 说明并请 A 确认。

文件解析（`extract_document`）属于 IN-03（#17），本模块不实现。
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, BinaryIO, Literal

from app.contracts import JobContent, Message, Profile, ProfileContent
from app.contracts.ports import (
    ConversationResult,
    ExtractedDocument,
    ModelGateway,
    StructuredResult,
    TaskContext,
)
from app.llm.schemas import task_output_schema

from .prompts import (
    JOB_EXTRACT_PROMPT,
    PROFILE_CHAT_PROMPT,
    PROFILE_EXTRACT_PROMPT,
)
from .synthetic import SYNTHETIC_SOURCE_ID
from .validation import validate_job_content, validate_profile_content

DEFAULT_TIMEOUT_SECONDS = 45.0
# 对话上下文只取最近 10 条用户消息（06-ai-contract.md「对话设计」）。
HISTORY_LIMIT = 10


class GatewayIntake:
    """用统一网关实现的 IntakePort；开发与测试默认接 FakeModelGateway。"""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        source_id: str = SYNTHETIC_SOURCE_ID,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        today: date | None = None,
    ):
        self._gateway = gateway
        self._source_id = source_id
        self._timeout = timeout_seconds
        self._today = today

    async def extract_document(self, handle: BinaryIO, media_type: str) -> ExtractedDocument:
        raise NotImplementedError("文件解析属于 IN-03（#17），本模块不实现。")

    async def build_profile(
        self,
        text: str,
        source_type: Literal["document", "message", "manual"],
        previous_profile: Profile | None = None,
        *,
        context: TaskContext,
    ) -> ProfileContent:
        prompt_context: dict[str, Any] = {
            "prompt": PROFILE_EXTRACT_PROMPT,
            "source_text": text,
            "source_type": source_type,
            "source_id": self._source_id,
            "current_month": self._current_month(),
        }
        if previous_profile is not None:
            prompt_context["previous_profile"] = previous_profile.model_dump(mode="json")

        result = await self._call("profile_extract", prompt_context, context)
        content = ProfileContent.model_validate(dict(result.data))
        return validate_profile_content(content, {self._source_id: text}, today=self._today).content

    async def advance_conversation(
        self,
        user_text: str,
        profile_content: ProfileContent,
        history_user_messages: Sequence[Message],
        *,
        context: TaskContext,
    ) -> ConversationResult:
        history = list(history_user_messages)[-HISTORY_LIMIT:]
        prompt_context: dict[str, Any] = {
            "prompt": PROFILE_CHAT_PROMPT,
            "profile_content": profile_content.model_dump(mode="json"),
            "history_user_messages": [message.content for message in history],
            "user_text": user_text,
            "message_source_id": self._source_id,
            "current_month": self._current_month(),
        }

        result = await self._call("profile_chat", prompt_context, context)
        payload = dict(result.data)
        updated = ProfileContent.model_validate(dict(payload["profile_content"]))
        # 证据可能来自历史消息，也可能来自本轮；两类来源都放进来源表再校验。
        sources = {message.id: message.content for message in history}
        sources[self._source_id] = user_text
        return ConversationResult(
            assistant_message=str(payload["assistant_message"]),
            profile_content=validate_profile_content(updated, sources, today=self._today).content,
        )

    async def extract_job(
        self,
        raw_text: str,
        company_context: str,
        *,
        context: TaskContext,
    ) -> JobContent:
        prompt_context: dict[str, Any] = {
            "prompt": JOB_EXTRACT_PROMPT,
            "raw_text": raw_text,
            "company_context": company_context,
        }

        result = await self._call("job_extract", prompt_context, context)
        content = JobContent.model_validate(dict(result.data))
        return validate_job_content(content, raw_text).content

    async def _call(
        self,
        task_name: str,
        prompt_context: Mapping[str, Any],
        context: TaskContext,
    ) -> StructuredResult:
        return await self._gateway.generate_structured(
            task_name,
            prompt_context,
            task_output_schema(task_name),
            self._timeout,
            context=context,
        )

    def _current_month(self) -> str:
        """与 validate_profile_content 的 today 用同一个日期来源。

        先前这里取 UTC 月份、校验取本地日期：在 UTC-5 等时区跨月时会不一致，
        AI 按 UTC 月份填的 as_of_month 会被判成"来自未来"。
        """
        return (self._today or date.today()).strftime("%Y-%m")
