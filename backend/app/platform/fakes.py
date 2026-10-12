"""Explicit API-01 port doubles. These do not implement M3/M4/M5 algorithms.

Intake preserves no invented facts; scoring deliberately marks every requirement
unknown. The fake score is zero, never an appraisal of the submitted material.
"""

import asyncio
from dataclasses import dataclass, field
from html import escape

from app.contracts import (
    DiagnosisItem,
    DimensionScore,
    Gap,
    JobContent,
    ProfileContent,
    ReportContent,
    Requirement,
    RequirementAssessment,
    ScoreResult,
)
from app.contracts.ports import ConversationResult, ExtractedDocument
from app.platform.errors import PlatformError


class FakeIntake:
    is_fake = True

    async def extract_document(self, handle, media_type):
        return ExtractedDocument("演示上传替身：未执行真实文档解析。", (), ())

    async def build_profile(self, text, source_type, previous_profile=None, *, context):
        return ProfileContent(
            overview=f"[演示数据] {text}",
            as_of_month=previous_profile.content.as_of_month if previous_profile else "2026-09",
            facts=[],
            evidence=[],
        )

    async def advance_conversation(
        self, user_text, profile_content, history_user_messages, *, context
    ):
        content = profile_content.model_copy(deep=True)
        content.overview = "[演示数据] 消息已保存；提取替身没有推断事实，请手动编辑确认。"
        return ConversationResult("[演示数据] 请检查并补充档案事实与原文证据。", content)

    async def extract_job(self, raw_text, company_context, *, context):
        return JobContent(
            title="[演示数据] 待手工核对的岗位",
            company_name=None,
            company_context=company_context,
            requirements=[
                Requirement(
                    id="fake-r1",
                    quote=raw_text,
                    category="other",
                    importance="preferred",
                    operator="manual_review",
                    target="演示占位要求",
                    ignored=False,
                    ignore_reason=None,
                    subject=None,
                )
            ],
        )


class FakeScoring:
    is_fake = True

    def assess_requirements(self, profile_content, job_content, matcher_version):
        return [
            RequirementAssessment(
                requirement_id=r.id,
                category=r.category,
                importance=r.importance,
                status="unknown",
                weight=2 if r.importance == "must" else 1,
                coefficient=0,
                evidence_ids=[],
                reason="演示评分替身未执行匹配；此结果不能用于评价求职者。",
            )
            for r in job_content.requirements
            if not r.ignored
        ]

    def calculate_score(self, assessments, rule_version):
        return ScoreResult(
            score=0,
            unknown_weight_ratio=1,
            rule_version=rule_version,
            matcher_version="matcher-v1",
            assessments=list(assessments),
            dimensions=[
                DimensionScore(category=c, score=0)
                for c in sorted({a.category for a in assessments})
            ],
        )


class FakeReporting:
    is_fake = True

    async def generate_report(
        self, profile_snapshot, job_snapshot, score_result, model_metadata, *, context
    ):
        return ReportContent(
            summary="[演示数据] 报告与评分均来自 API-01 替身；请勿作为真实诊断结论。",
            gaps=[
                Gap(
                    requirement_id=a.requirement_id,
                    kind="needs_evidence",
                    description="[演示数据] 等待真实匹配模块校验。",
                    evidence_ids=[],
                )
                for a in score_result.assessments
            ],
            suggestions=[],
            actions=[],
        )

    def export_markdown(self, item: DiagnosisItem) -> str:
        text = f"## 岗位 {item.job.id} / v{item.job.version}\n\n状态：{item.status}\n\n"
        if item.score_result:
            text += f"演示评分：{item.score_result.score}\n规则：{escape(item.score_result.rule_version)}\n\n"
            text += f"匹配版本：{escape(item.score_result.matcher_version)}\n未知比例：{item.score_result.unknown_weight_ratio}\n\n"
            for assessment in item.score_result.assessments:
                reason = escape(assessment.reason).replace("\n", " ")
                text += f"- {escape(assessment.requirement_id)}：{assessment.status}；权重 {assessment.weight}；系数 {assessment.coefficient}；{reason}\n"
            text += "\n"
        if item.model_metadata:
            metadata = item.model_metadata
            text += f"供应商：{escape(metadata.provider)}\n实际模型：{escape(metadata.model)}\n"
            text += f"提示版本：{escape(metadata.prompt_version)}\n配置版本：{escape(metadata.gateway_config_version)}\n\n"
        if item.report:
            text += escape(item.report.summary) + "\n\n"
        if item.error:
            text += f"报告或评分失败：{escape(item.error.code)}\n\n"
        return text


@dataclass
class FakeTaskExecutor:
    """Injectable pause/failure control. Controls are never read from user input."""

    delay_seconds: float = 0.01
    gate: asyncio.Event | None = None
    failures: dict[str, str] = field(default_factory=dict)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    is_fake: bool = True

    async def before(self, operation: str) -> None:
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if operation in self.failures:
            raise PlatformError(422, self.failures[operation], "演示替身的可控失败")
