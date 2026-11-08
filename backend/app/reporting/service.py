"""Model-authored report analysis and Markdown export.

The current enhancement path checks only shape and reference integrity. Historical
`generate_report` remains available for legacy clients with its original contract.
Frozen scores are never changed by model output; privacy filtering applies to both.
"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from app.contracts import DiagnosisItem, Job, ModelMetadata, Profile, ReportContent, ScoreResult
from app.contracts.ports import ModelGateway, ReportingPort, TaskContext
from app.diagnostics import capture_output, locate, log_rejection, pydantic_issues, report_trace
from app.llm.errors import GatewayError
from app.llm.schemas import task_output_schema

from .enhancement import (
    ENHANCEMENT_POLICY_VERSION,
    ENHANCEMENT_PROMPT,
    EnhancedReport,
)
from .errors import ReportError
from .explanation import ReportAdvice, assemble_report, mark_omitted
from .grounding import build_grounding_review
from .markdown import export_markdown as render_markdown
from .privacy import REDACTED_QUOTE, filter_report_context
from .prompts import REPORT_PROMPT, REPORT_PROMPT_VERSION
from .validation import GAP_KIND_BY_STATUS, validate_report

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
        diagnostic_observer: Callable[[Mapping[str, Any]], None] | None = None,
    ):
        self._gateway = gateway
        self._timeout = timeout_seconds
        self._privacy_filter = privacy_filter
        self._diagnostic_observer = diagnostic_observer

    @staticmethod
    def build_base_report(
        profile_snapshot: Profile, job_snapshot: Job, score_result: ScoreResult
    ) -> ReportContent:
        """Render frozen scoring without model configuration or model calls."""
        report = ReportContent.model_validate(
            assemble_report({"suggestions": [], "actions": []}, score_result)
        )
        validate_report(report, profile_snapshot.content, job_snapshot.content, score_result)
        return report

    async def generate_enhancement(
        self,
        profile_snapshot: Profile,
        job_snapshot: Job,
        score_result: ScoreResult,
        model_metadata: ModelMetadata,
        *,
        context: TaskContext,
        requirement_ids: list[str] | None = None,
    ) -> ReportContent:
        """Generate direct analysis without a second semantic review request."""
        with report_trace(
            self._diagnostic_observer,
            profile_id=profile_snapshot.id,
            job_id=job_snapshot.id,
            profile_version=profile_snapshot.version,
            job_version=job_snapshot.version,
            prompt_version=ENHANCEMENT_POLICY_VERSION,
            gateway_version=model_metadata.gateway_config_version,
        ) as trace_id:
            try:
                return await self._enhance(
                    profile_snapshot,
                    job_snapshot,
                    score_result,
                    model_metadata,
                    context=context,
                    requirement_ids=requirement_ids,
                )
            except Exception as error:
                error.report_trace_id = trace_id
                log_rejection(error, phase="enhancement_return")
                raise

    async def _enhance(self, profile, job, score, metadata, *, context, requirement_ids):
        all_ids = {r.id for r in job.content.requirements if not r.ignored}
        selected = set(requirement_ids or all_ids)
        if not selected <= all_ids:
            raise ReportError("VALIDATION_ERROR", "所选要求不属于当前岗位")
        prompt_context = self._prompt_context(profile, job, score)
        prompt_context.pop("gap_constraints", None)
        prompt_context.pop("suggestion_policy", None)
        prompt_context.pop("score_result", None)
        prompt_context["current_date"] = metadata.generated_at[:10]
        prompt_context["job_snapshot"]["raw_text"] = job.raw_text
        prompt_context["prompt_version"] = ENHANCEMENT_POLICY_VERSION
        sent, _ = self._filtered(prompt_context)
        sent.update(
            prompt=ENHANCEMENT_PROMPT,
            enhancement_policy_version=ENHANCEMENT_POLICY_VERSION,
            selected_requirement_ids=sorted(selected),
        )
        # The model owns the analysis and wording. Only the output shape and
        # identifiers are checked; there is no second semantic reviewer.
        response = await self._gateway.generate_structured(
            "diagnosis_report",
            sent,
            ReportContent.model_json_schema(),
            self._timeout,
            context=context,
        )
        self._check_metadata(response.model_metadata, metadata, context)
        result = EnhancedReport.model_validate(dict(response.data))
        from app.platform.enhancements import validate_candidate

        validate_candidate(result, profile, job, score, selected)
        capture_output("enhancement.final", result.model_dump(mode="json"))
        return result

    async def generate_report(
        self,
        profile_snapshot: Profile,
        job_snapshot: Job,
        score_result: ScoreResult,
        model_metadata: ModelMetadata,
        *,
        context: TaskContext,
    ) -> ReportContent:
        with report_trace(
            self._diagnostic_observer,
            profile_id=profile_snapshot.id,
            job_id=job_snapshot.id,
            profile_version=profile_snapshot.version,
            job_version=job_snapshot.version,
            prompt_version=model_metadata.prompt_version,
            gateway_version=model_metadata.gateway_config_version,
        ) as trace_id:
            try:
                return await self._generate_report(
                    profile_snapshot, job_snapshot, score_result, model_metadata, context=context
                )
            except Exception as error:
                error.report_trace_id = trace_id
                log_rejection(error, phase="report_return")
                raise

    async def _generate_report(
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

        def check_output(raw):
            try:
                content = ReportContent.model_validate(dict(raw))
            except ValidationError as error:
                raise GatewayError(
                    "MODEL_OUTPUT_INVALID",
                    "报告结构未通过校验",
                    reason_code="SCHEMA_INVALID",
                    issues=pydantic_issues(error),
                ) from None
            try:
                validate_report(
                    content,
                    profile_snapshot.content,
                    job_snapshot.content,
                    score_result,
                    redacted_evidence=redacted_evidence,
                )
            except ReportError as error:
                raise GatewayError(
                    error.code,
                    "报告内容未通过校验",
                    reason_code=error.reason_code,
                    issues=error.issues,
                ) from None

        reviewed = getattr(self._gateway, "generate_reviewed", None)
        omitted_by_validation = False

        def prepare_advice(raw):
            nonlocal omitted_by_validation
            if score_result.rule_version != "coverage-v3":
                return assemble_report(
                    self._limit_optional_items(
                        raw, supported_facts_only=score_result.rule_version == "coverage-v2"
                    ),
                    score_result,
                )
            base = assemble_report({"suggestions": [], "actions": []}, score_result)
            # Never discard a mandatory/core failure as if it were optional advice.
            validate_report(
                ReportContent.model_validate(base),
                profile_snapshot.content,
                job_snapshot.content,
                score_result,
                redacted_evidence=redacted_evidence,
            )
            omitted = False
            for kind in ("suggestions", "actions"):
                for index, value in enumerate(raw[kind][:3]):
                    trial = deepcopy(base)
                    trial[kind] = [value]
                    try:
                        validate_report(
                            ReportContent.model_validate(trial),
                            profile_snapshot.content,
                            job_snapshot.content,
                            score_result,
                            redacted_evidence=redacted_evidence,
                        )
                    except ReportError as error:
                        if not error.issues or any(
                            not i.path.startswith(f"/{kind}/0") for i in error.issues
                        ):
                            raise
                        error.issues = tuple(
                            replace(i, path=i.path.replace(f"/{kind}/0", f"/{kind}/{index}", 1))
                            for i in error.issues
                        )
                        log_rejection(error, phase="generation.optional_filtered", candidate=raw)
                        omitted = True
                    else:
                        base[kind].append(value)
            omitted_by_validation = omitted
            capture_output("generation.prepared", base)
            return base

        if callable(reviewed):
            result = await reviewed(
                "diagnosis_report",
                sent,
                ReportAdvice.model_json_schema(),
                self._timeout,
                context=context,
                validate_output=check_output,
                build_review=lambda candidate: build_grounding_review(
                    candidate, sent, allow_partial_advice=score_result.rule_version == "coverage-v3"
                ),
                prepare_output=prepare_advice,
            )
        elif getattr(self._gateway, "is_fake", False) is True and model_metadata.provider == "fake":
            # Synthetic development outputs exercise the deterministic guards only.
            # They are explicitly marked fake; this is not a semantic-review result.
            result = await self._gateway.generate_structured(
                "diagnosis_report",
                sent,
                task_output_schema("diagnosis_report"),
                self._timeout,
                context=context,
            )
        else:
            raise ReportError(
                "MODEL_OUTPUT_INVALID",
                "当前模型网关不支持独立事实核对，已保留规则评分。",
            )
        capture_output("report.candidate", dict(result.data))
        self._check_metadata(result.model_metadata, model_metadata, context)

        try:
            report = ReportContent.model_validate(dict(result.data))
        except ValidationError as error:
            raise ReportError(
                "MODEL_OUTPUT_INVALID",
                "报告输出不符合 ReportContent 结构",
                reason_code="SCHEMA_INVALID",
                issues=pydantic_issues(error),
            ) from None

        if omitted_by_validation:
            report = ReportContent.model_validate(mark_omitted(report.model_dump(mode="json")))

        validate_report(
            report,
            profile_snapshot.content,
            job_snapshot.content,
            score_result,
            redacted_evidence=redacted_evidence,
        )
        if score_result.model_dump(mode="json") != frozen_score:
            raise ReportError(
                "MODEL_OUTPUT_INVALID",
                "报告生成过程改动了冻结评分",
                issues=(locate(("score_result",), "FROZEN_SCORE_MUTATED"),),
            )
        capture_output("report.final", report.model_dump(mode="json"))
        return report

    def export_markdown(self, item: DiagnosisItem) -> str:
        return render_markdown(item)

    @staticmethod
    def _limit_optional_items(
        raw: dict[str, Any], *, supported_facts_only: bool = False
    ) -> dict[str, Any]:
        # Only optional advice is bounded. All mandatory gaps stay intact, and
        # retained claims still pass the original evidence and semantic guards.
        if supported_facts_only and isinstance(raw.get("suggestions"), list):
            # Unsupported templates are optional, so discard them instead of
            # paying to regenerate the complete report. Retained prose is reviewed.
            raw["suggestions"] = [
                item
                for item in raw["suggestions"]
                if not isinstance(item, dict) or item.get("requires_user_input") is not True
            ]
        for name in ("suggestions", "actions"):
            if isinstance(raw.get(name), list):
                raw[name] = raw[name][:3]
        return raw

    @staticmethod
    def _prompt_context(
        profile_snapshot: Profile,
        job_snapshot: Job,
        score_result: ScoreResult,
    ) -> dict[str, Any]:
        profile_content = profile_snapshot.content.model_dump(mode="json", exclude_none=True)
        # Reports reference evidence IDs, not upload IDs or file locations. Quotes
        # remain complete; the immutable persisted snapshot retains all metadata.
        profile_content["evidence"] = [
            {"id": item.id, "quote": item.quote} for item in profile_snapshot.content.evidence
        ]
        return {
            "prompt": REPORT_PROMPT,
            "prompt_version": REPORT_PROMPT_VERSION,
            "profile_snapshot": {
                "id": profile_snapshot.id,
                "version": profile_snapshot.version,
                "content": profile_content,
            },
            "job_snapshot": {
                "id": job_snapshot.id,
                "version": job_snapshot.version,
                "content": job_snapshot.content.model_dump(mode="json"),
            },
            "score_result": score_result.model_dump(mode="json"),
            "suggestion_policy": "supported_facts_only"
            if score_result.rule_version in {"coverage-v2", "coverage-v3"}
            else "conditional_templates_allowed",
            "gap_constraints": [
                {
                    "requirement_id": item.requirement_id,
                    "kind": GAP_KIND_BY_STATUS.get(item.status),
                    "required": item.importance == "must",
                    "unknown_reason": item.unknown_reason,
                    "counted_in_score": item.counted_in_score,
                    "allowed_evidence_ids": list(item.evidence_ids),
                }
                for item in score_result.assessments
                if item.status != "met"
            ],
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
