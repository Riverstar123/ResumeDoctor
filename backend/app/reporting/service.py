"""M5 报告服务：通过统一网关生成并校验诊断报告，同时提供 Markdown 导出。

`ReportService` 实现共享的 `ReportingPort`（docs/02-architecture.md「内部端口」）：

- `generate_report` 接收已确认的冻结 Profile/Job 快照和不可修改的 ScoreResult，
  组织 `diagnosis_report` 提示上下文，调用 `ModelGateway`，再按冻结契约做结构
  与语义校验。失败原样上抛网关错误，由 M2 把岗位降级为 score_only，保留评分。
- `export_markdown` 只读已存储的 DiagnosisItem，不访问模型、数据库或网络。

开发与测试默认注入 `FakeModelGateway`；真实适配器由 AI-02 提供，本模块不读取
任何密钥或供应商配置。非 fake 网关必须显式配置经过评审的隐私过滤策略。
"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from app.contracts import DiagnosisItem, Job, ModelMetadata, Profile, ReportContent, ScoreResult
from app.contracts.ports import ModelGateway, ReportingPort, StructuredResult, TaskContext
from app.llm.schemas import task_output_schema

from .errors import ReportError
from .markdown import export_markdown as render_markdown
from .privacy import REDACTED_QUOTE, filter_report_context
from .prompts import REPORT_PROMPT, REPORT_PROMPT_VERSION
from .validation import validate_report

DEFAULT_TIMEOUT_SECONDS = 45.0
# generated_at 允许因本次调用而变化；其余映射字段必须与任务冻结快照完全一致。
MODEL_MAPPING_FIELDS = (
    "model_id",
    "provider",
    "model",
    "prompt_version",
    "gateway_config_version",
)


class ReportService(ReportingPort):
    """可注入的报告生成与导出实现；不持有任何用户会话状态。"""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        privacy_filter: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ):
        self._gateway = gateway
        self._timeout = timeout_seconds
        self._privacy_filter = privacy_filter

    async def generate_report(
        self,
        profile_snapshot: Profile,
        job_snapshot: Job,
        score_result: ScoreResult,
        model_metadata: ModelMetadata,
        *,
        context: TaskContext,
    ) -> ReportContent:
        frozen_score = score_result.model_dump(mode="json")
        prompt_context = self._prompt_context(profile_snapshot, job_snapshot, score_result)
        sent, redacted_evidence = self._filtered(prompt_context)

        result: StructuredResult = await self._gateway.generate_structured(
            "diagnosis_report",
            sent,
            task_output_schema("diagnosis_report"),
            self._timeout,
            context=context,
        )
        self._check_metadata(result.model_metadata, model_metadata, context)

        try:
            report = ReportContent.model_validate(dict(result.data))
        except (ValidationError, TypeError, ValueError):
            raise ReportError("MODEL_OUTPUT_INVALID", "报告输出不符合 ReportContent 结构") from None

        validate_report(
            report,
            profile_snapshot.content,
            job_snapshot.content,
            score_result,
            redacted_evidence=redacted_evidence,
        )
        if score_result.model_dump(mode="json") != frozen_score:
            raise ReportError("MODEL_OUTPUT_INVALID", "报告生成过程改动了冻结评分")
        return report

    def export_markdown(self, item: DiagnosisItem) -> str:
        return render_markdown(item)

    @staticmethod
    def _prompt_context(
        profile_snapshot: Profile,
        job_snapshot: Job,
        score_result: ScoreResult,
    ) -> dict[str, Any]:
        return {
            "prompt": REPORT_PROMPT,
            "prompt_version": REPORT_PROMPT_VERSION,
            "profile_snapshot": {
                "id": profile_snapshot.id,
                "version": profile_snapshot.version,
                "content": profile_snapshot.content.model_dump(mode="json"),
            },
            "job_snapshot": {
                "id": job_snapshot.id,
                "version": job_snapshot.version,
                "content": job_snapshot.content.model_dump(mode="json"),
            },
            "score_result": score_result.model_dump(mode="json"),
        }

    def _filtered(self, prompt_context: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        if self._privacy_filter is not None:
            filtered = self._privacy_filter(prompt_context)
        else:
            if getattr(self._gateway, "is_fake", False) is not True:
                raise ReportError(
                    "PRIVACY_FILTER_REQUIRED",
                    "非 fake 网关必须显式配置已评审的报告隐私过滤策略。",
                )
            filtered = filter_report_context(prompt_context)

        filtered = deepcopy(dict(filtered))
        redacted_evidence: dict[str, str] = {}
        content = (filtered.get("profile_snapshot") or {}).get("content") or {}
        for item in content.get("evidence") or []:
            evidence_id = item.get("id")
            if evidence_id is None:
                continue
            if not item.get("quote"):
                # Evidence.quote 不能为空；这个标记不是新的用户证据。
                item["quote"] = REDACTED_QUOTE
            redacted_evidence[evidence_id] = item["quote"]
        return filtered, redacted_evidence

    @staticmethod
    def _check_metadata(
        resolved: ModelMetadata,
        frozen: ModelMetadata,
        context: TaskContext,
    ) -> None:
        # 不静默换模型：任务入队时冻结的 model_id 必须与本次调用一致。
        if frozen.model_id != context.model_id or resolved.model_id != context.model_id:
            raise ReportError("MODEL_UNAVAILABLE", "报告模型与任务冻结的 model_id 不一致")
        # 同一公开 id 的实际 provider/model/配置变化同样不能静默接受，
        # 否则报告展示和导出的来源会与真实网关不符。
        if any(
            getattr(frozen, field) != getattr(resolved, field) for field in MODEL_MAPPING_FIELDS
        ):
            raise ReportError("MODEL_UNAVAILABLE", "报告模型映射与任务冻结快照不一致")
        if resolved.prompt_version != REPORT_PROMPT_VERSION:
            raise ReportError("MODEL_OUTPUT_INVALID", "报告提示版本与报告提示词不一致")
