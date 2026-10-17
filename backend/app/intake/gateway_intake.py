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

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
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

from .errors import IntakeError
from .privacy import filter_fake_context
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
        privacy_filter: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ):
        self._gateway = gateway
        self._source_id = source_id
        self._timeout = timeout_seconds
        self._today = today
        self._privacy_filter = privacy_filter

    def _filtered(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._privacy_filter is not None:
            filtered = self._privacy_filter(value)
        else:
            if getattr(self._gateway, "is_fake", False) is not True:
                raise IntakeError(
                    "PRIVACY_FILTER_REQUIRED", "非 fake 网关必须显式配置已评审的隐私过滤策略。"
                )
            filtered = filter_fake_context(value)
        filtered = deepcopy(dict(filtered))
        # Keep the old evidence projection echoable under the frozen output
        # Schema. This marker is only transport data, never new source evidence.
        previous = (filtered.get("previous_profile") or {}).get("content")
        for snapshot in (filtered.get("profile_content"), previous):
            if snapshot is not None:
                for item in snapshot["evidence"]:
                    if item["quote"] == "":
                        item["quote"] = "[联系方式已过滤]"
        return filtered

    def _validate_draft(self, content, previous, sources, source_types, filtered_previous=None):
        # The caller owns the verified previous snapshot. Never trust a changed
        # quote merely because a model reused an old evidence ID.
        inherited = {item.id: item for item in previous.evidence} if previous else {}
        # A privacy projection is not a persistable DTO. Compare its plain
        # records with the response, then restore only the exact trusted item.
        projection = filtered_previous or {}
        filtered_evidence = {item["id"]: item for item in projection.get("evidence", [])}
        restored = content.model_copy(deep=True)
        for index, item in enumerate(restored.evidence):
            if item.id in inherited:
                if item.model_dump(mode="json") == filtered_evidence.get(item.id):
                    restored.evidence[index] = inherited[item.id].model_copy(deep=True)
                elif item != inherited[item.id]:
                    raise IntakeError("MODEL_OUTPUT_INVALID", "模型改动了既有证据。")
            elif item.source_id in source_types:
                if item.source_type != source_types[item.source_id]:
                    raise IntakeError("INVALID_SOURCE_TYPE", "证据来源类型与输入原文不一致。")
        if previous is not None:
            previous_facts = {fact.id: fact for fact in previous.facts}
            projected_facts = {item["id"]: item for item in projection.get("facts", [])}
            for index, fact in enumerate(restored.facts):
                if fact.id in previous_facts and (
                    fact.model_dump(mode="json") == projected_facts.get(fact.id)
                ):
                    restored.facts[index] = previous_facts[fact.id].model_copy(deep=True)
            if not {fact.id for fact in previous.facts} <= {fact.id for fact in restored.facts}:
                raise IntakeError("MODEL_OUTPUT_INVALID", "模型遗漏了既有事实，请重试或手工编辑。")
            returned = {item.id: item for item in restored.evidence}
            if any(returned.get(key) != item for key, item in inherited.items()):
                raise IntakeError("MODEL_OUTPUT_INVALID", "模型遗漏或改动了既有证据。")
        validated = validate_profile_content(
            restored,
            sources,
            today=self._today,
            previously_verified_evidence=tuple(inherited.values()),
        ).content
        if previous is not None:
            old_sources = {item.source_id for item in previous.evidence}
            new_evidence_ids = {
                item.id
                for item in validated.evidence
                if item.id not in inherited and item.source_id not in old_sources
            }
            for fact in validated.facts:
                if (
                    fact.id in previous_facts
                    and fact != previous_facts[fact.id]
                    and not new_evidence_ids.intersection(fact.evidence_ids)
                ):
                    raise IntakeError(
                        "MODEL_OUTPUT_INVALID", "模型改动了既有事实，但未引用新增用户来源的证据。"
                    )
        return validated

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

        result, sent = await self._call("profile_extract", prompt_context, context)
        content = ProfileContent.model_validate(dict(result.data))
        return self._validate_draft(
            content,
            previous_profile.content if previous_profile else None,
            {self._source_id: text},
            {self._source_id: source_type},
            (sent.get("previous_profile") or {}).get("content"),
        )

    async def advance_conversation(
        self,
        user_text: str,
        profile_content: ProfileContent,
        history_user_messages: Sequence[Message],
        *,
        context: TaskContext,
    ) -> ConversationResult:
        history = [message for message in history_user_messages if message.role == "user"][
            -HISTORY_LIMIT:
        ]
        prompt_context: dict[str, Any] = {
            "prompt": PROFILE_CHAT_PROMPT,
            "profile_content": profile_content.model_dump(mode="json"),
            # Keep each text and its source ID together, without duplicating
            # the text in a second mapping and consuming the input budget twice.
            "history_user_messages": [
                {"source_id": message.id, "content": message.content} for message in history
            ],
            "user_text": user_text,
            "message_source_id": self._source_id,
            "current_month": self._current_month(),
        }

        result, sent = await self._call("profile_chat", prompt_context, context)
        payload = dict(result.data)
        updated = ProfileContent.model_validate(dict(payload["profile_content"]))
        # 证据可能来自历史消息，也可能来自本轮；两类来源都放进来源表再校验。
        sources = {message.id: message.content for message in history}
        sources[self._source_id] = user_text
        return ConversationResult(
            assistant_message=str(payload["assistant_message"]),
            profile_content=self._validate_draft(
                updated,
                profile_content,
                sources,
                {**{message.id: "message" for message in history}, self._source_id: "message"},
                sent.get("profile_content"),
            ),
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

        result, _ = await self._call("job_extract", prompt_context, context)
        content = JobContent.model_validate(dict(result.data))
        return validate_job_content(content, raw_text).content

    async def _call(
        self,
        task_name: str,
        prompt_context: Mapping[str, Any],
        context: TaskContext,
    ) -> tuple[StructuredResult, Mapping[str, Any]]:
        filtered = self._filtered(prompt_context)
        result = await self._gateway.generate_structured(
            task_name,
            filtered,
            task_output_schema(task_name),
            self._timeout,
            context=context,
        )
        return result, filtered

    def _current_month(self) -> str:
        """与 validate_profile_content 的 today 用同一个日期来源。

        先前这里取 UTC 月份、校验取本地日期：在 UTC-5 等时区跨月时会不一致，
        AI 按 UTC 月份填的 as_of_month 会被判成"来自未来"。
        """
        return (self._today or date.today()).strftime("%Y-%m")
