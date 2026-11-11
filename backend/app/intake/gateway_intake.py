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

文件解析（IN-03）由独立的限额解析进程处理；不保存或删除调用方的文件。
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import date
from typing import Any, BinaryIO, Literal

from app.business_calendar import business_today
from app.contracts import Evidence, FollowUpMatch, JobContent, Message, Profile, ProfileContent
from app.contracts.ports import (
    ConversationResult,
    DiagnosisFocusContext,
    ExtractedDocument,
    ModelGateway,
    StructuredResult,
    TaskContext,
)
from app.llm.errors import GatewayError
from app.llm.schemas import task_output_schema
from app.structured_fields import (
    defer_uncertain_attributes,
    validate_attributes,
    validate_condition,
)

from .documents import DocumentExtractor, DocumentLimits, locate_document_evidence
from .errors import IntakeError
from .privacy import filter_fake_context
from .prompts import (
    DIAGNOSIS_FOLLOWUP_PROMPT,
    JOB_EXTRACT_PROMPT,
    PROFILE_CHAT_PROMPT,
    PROFILE_EXTRACT_PROMPT,
)
from .synthetic import SYNTHETIC_SOURCE_ID
from .validation import validate_job_content, validate_profile_content

DEFAULT_TIMEOUT_SECONDS = 45.0
# 用户证据与助手只读上下文各保留最近 10 条，避免互相挤占窗口。
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
        document_limits: DocumentLimits | None = None,
    ):
        self._gateway = gateway
        self._source_id = source_id
        self._timeout = timeout_seconds
        self._today = today
        self._privacy_filter = privacy_filter
        self._documents = DocumentExtractor(document_limits)

    def for_source(self, source_id: str) -> "GatewayIntake":
        """Bind one in-memory task's source without mutating a shared adapter."""
        from copy import copy

        result = copy(self)
        result._source_id = source_id
        return result

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

    @staticmethod
    def _attribute_evidence(content, sources, source_types, previous=None):
        """Materialize model-quoted attributes as source-verified evidence.

        This only repairs an omitted evidence ID, never a quote/value. Old facts
        remain immutable; new attribute quotes must be literal current input spans.
        """
        result = content.model_copy(deep=True)
        old = {f.id: f for f in previous.facts} if previous else {}
        for fact in result.facts:
            if fact.id in old and fact == old[fact.id]:
                continue
            for attribute in fact.attributes:
                if any(
                    attribute.quote in e.quote for e in result.evidence if e.id in fact.evidence_ids
                ):
                    continue
                source_id = next(
                    (key for key, text in sources.items() if attribute.quote in text), None
                )
                if source_id is None:
                    continue  # Ordinary validation rejects an unsupported quote.
                evidence = next(
                    (
                        e
                        for e in result.evidence
                        if e.quote == attribute.quote and e.source_id == source_id
                    ),
                    None,
                )
                if evidence is None:
                    ids = {e.id for e in result.evidence}
                    number = 1
                    while f"attribute-e{number}" in ids:
                        number += 1
                    evidence = Evidence(
                        id=f"attribute-e{number}",
                        source_id=source_id,
                        source_type=source_types[source_id],
                        quote=attribute.quote,
                        locator=None,
                    )
                    result.evidence.append(evidence)
                if evidence.id not in fact.evidence_ids:
                    fact.evidence_ids.append(evidence.id)
        return ProfileContent.model_validate(result.model_dump())

    async def extract_document(self, handle: BinaryIO, media_type: str) -> ExtractedDocument:
        return await self._documents.extract(handle, media_type)

    async def build_document_profile(
        self,
        document: ExtractedDocument,
        previous_profile: Profile | None = None,
        *,
        context: TaskContext,
    ) -> ProfileContent:
        """Optional M2 integration helper; uses the existing build_profile port.

        This is stateless: different users' extracted segments are never stored
        on the shared adapter. source_id must be bound to this request by M2.
        """
        content = await self.build_profile(
            document.text, "document", previous_profile, context=context
        )
        return locate_document_evidence(content, document, self._source_id)

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
        diagnosis_focus: DiagnosisFocusContext | None = None,
        questions_only: bool = False,
    ) -> ConversationResult:
        if questions_only and diagnosis_focus is None:
            raise IntakeError("MODEL_OUTPUT_INVALID", "定向提问缺少已核验的岗位上下文。")
        history = [message for message in history_user_messages if message.role == "user"][
            -HISTORY_LIMIT:
        ]
        assistant_history = [
            message for message in history_user_messages if message.role == "assistant"
        ][-HISTORY_LIMIT:]
        selected = {message.id for message in [*history, *assistant_history]}
        prompt_context: dict[str, Any] = {
            "prompt": PROFILE_CHAT_PROMPT,
            "profile_content": profile_content.model_dump(mode="json"),
            # Keep each text and its source ID together, without duplicating
            # the text in a second mapping and consuming the input budget twice.
            "history_user_messages": [
                {"source_id": message.id, "content": message.content} for message in history
            ],
            "history_assistant_messages": [
                {"message_id": message.id, "content": message.content}
                for message in assistant_history
            ],
            "history_order": [
                message.id for message in history_user_messages if message.id in selected
            ],
            "user_text": user_text,
            "message_source_id": self._source_id,
            "current_month": self._current_month(),
        }

        if diagnosis_focus is not None:
            prompt_context["prompt"] = PROFILE_CHAT_PROMPT + DIAGNOSIS_FOLLOWUP_PROMPT
            prompt_context["diagnosis_focus"] = diagnosis_focus.model_dump(mode="json")
            prompt_context["questions_only"] = questions_only
        if questions_only:
            prompt_context["user_text"] = ""
            prompt_context.pop("message_source_id")

        result, sent = await self._call("profile_chat", prompt_context, context)
        payload = dict(result.data)
        updated = ProfileContent.model_validate(dict(payload["profile_content"]))
        if questions_only:
            # The model saw only the privacy projection. It must echo every
            # field exactly; only the server can restore the trusted original.
            if updated.model_dump(mode="json") != sent["profile_content"]:
                raise IntakeError("MODEL_OUTPUT_INVALID", "提问阶段不得增加、删改档案事实或证据。")
            return ConversationResult(
                assistant_message=str(payload["assistant_message"]),
                profile_content=profile_content.model_copy(deep=True),
            )
        # 证据可能来自历史消息，也可能来自本轮；两类来源都放进来源表再校验。
        sources = {message.id: message.content for message in history}
        source_types = {message.id: "message" for message in history}
        sources[self._source_id] = user_text
        source_types[self._source_id] = "message"
        validated = self._validate_draft(
            updated, profile_content, sources, source_types, sent.get("profile_content")
        )
        match = payload.get("followup_match") if diagnosis_focus is not None else None
        return ConversationResult(
            assistant_message=str(payload["assistant_message"]),
            profile_content=validated,
            followup_match=FollowUpMatch.model_validate(match) if match is not None else None,
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

        def normalize(raw):
            data = deepcopy(dict(raw))
            if task_name == "profile_extract":
                content = ProfileContent.model_validate(data)
                previous = filtered.get("previous_profile")
                previous = ProfileContent.model_validate(previous["content"]) if previous else None
                content = self._attribute_evidence(
                    content,
                    {self._source_id: filtered["source_text"]},
                    {self._source_id: filtered["source_type"]},
                    previous,
                )
                return defer_uncertain_attributes(content).model_dump(mode="json")
            if task_name == "profile_chat" and not filtered.get("questions_only"):
                previous = ProfileContent.model_validate(filtered["profile_content"])
                data["profile_content"] = self._attribute_evidence(
                    ProfileContent.model_validate(data["profile_content"]),
                    {self._source_id: filtered["user_text"]},
                    {self._source_id: "message"},
                    previous,
                ).model_dump(mode="json")
                data["profile_content"] = defer_uncertain_attributes(
                    ProfileContent.model_validate(data["profile_content"])
                ).model_dump(mode="json")
            return data

        def check_attributes(raw):
            try:
                raw = normalize(raw)
                if task_name in {"profile_extract", "profile_chat"}:
                    payload = raw if task_name == "profile_extract" else raw["profile_content"]
                    content = ProfileContent.model_validate(payload)
                    for fact in content.facts:
                        validate_attributes(
                            fact,
                            [e.quote for e in content.evidence if e.id in fact.evidence_ids],
                            evidence=[e for e in content.evidence if e.id in fact.evidence_ids],
                        )
                elif task_name == "job_extract":
                    for requirement in JobContent.model_validate(raw).requirements:
                        validate_condition(requirement)
            except (ValueError, KeyError):
                raise GatewayError(
                    "MODEL_OUTPUT_INVALID",
                    "结构化属性未通过核对",
                    reason_code="STRUCTURED_ATTRIBUTE_INVALID",
                ) from None

        validated = getattr(self._gateway, "generate_validated", None)
        call = validated if callable(validated) else self._gateway.generate_structured
        kwargs = {"validate_output": check_attributes} if callable(validated) else {}
        result = await call(
            task_name,
            filtered,
            task_output_schema(task_name),
            self._timeout,
            context=context,
            **kwargs,
        )
        result = StructuredResult(data=normalize(result.data), model_metadata=result.model_metadata)
        payload = (
            result.data if task_name == "profile_extract" else result.data.get("profile_content")
        )
        if isinstance(payload, Mapping):
            for index, fact in enumerate(payload.get("facts", [])):
                for attribute in fact.get("unverified_attributes", []):
                    logging.getLogger(__name__).info(
                        "intake_attribute_pending task=%s fact_index=%d field=%s",
                        task_name,
                        index,
                        attribute["name"],
                    )
        return result, filtered

    def _current_month(self) -> str:
        """与前端、M2 和语义校验共用北京时间，保留显式 today 测试注入。"""
        return (self._today or business_today()).strftime("%Y-%m")
