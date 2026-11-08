"""Direct model analysis: shape/scope validation, without semantic rejection."""

import asyncio
import json

import httpx
import pytest

from app.contracts import ReportContent
from app.contracts.ports import TaskContext
from app.llm import build_llm
from app.platform.enhancements import merge_advice, validate_candidate
from app.reporting import ReportError, ReportService
from app.reporting.privacy import filter_report_context
from tests.llm.test_real_gateway import ok, real_settings


def test_base_report_needs_no_model_configuration_and_preserves_inputs(snapshots):
    profile, job, item = snapshots

    class ForbiddenGateway:
        def __getattr__(self, _):
            raise AssertionError("base report must not inspect a gateway")

    service = ReportService(ForbiddenGateway())
    frozen = [x.model_dump() for x in (profile, job, item.score_result)]
    base = service.build_base_report(profile, job, item.score_result)
    assert base.summary and base.gaps and base.suggestions == base.actions == []
    assert frozen == [x.model_dump() for x in (profile, job, item.score_result)]


def test_base_does_not_hide_broken_scoring_references(snapshots):
    profile, job, item = snapshots
    score = item.score_result.model_copy(deep=True)
    score.assessments[0].evidence_ids = ["missing"]
    with pytest.raises(ReportError):
        ReportService.build_base_report(profile, job, score)


def test_base_and_failed_enhancement_export_are_separate(snapshots):
    from app.contracts.models import EnhancementState, ErrorInfo
    from app.reporting.markdown import export_markdown

    profile, job, item = snapshots
    item.report = ReportService.build_base_report(profile, job, item.score_result)
    item.model_metadata = None
    item.enhancement = EnhancementState(
        task_id=item.id,
        model_id="real-default",
        status="failed",
        requirement_ids=[],
        error=ErrorInfo(code="MODEL_TIMEOUT", message="本次建议未完成"),
        model_metadata=None,
    )
    text = export_markdown(item)
    assert "基础诊断" in text and "基础报告仍可使用" in text
    assert "AI 报告未生成" not in text and "模型与版本" not in text
    assert "总分：66.7 / 100" in text


@pytest.mark.parametrize("native", [False, True])
def test_model_owns_analysis_and_rewrites_in_one_request(snapshots, native):
    from tests.llm.test_structured_output import tool_result

    profile, job, item = snapshots
    rid = job.content.requirements[0].id
    eid = profile.content.evidence[0].id
    payload = dict(
        summary="已有经历与岗位相关，建议突出工具使用场景，而不是重复技能名称。",
        gaps=[
            dict(
                requirement_id=rid,
                kind="needs_evidence",
                description="请说明项目中你负责的部分。",
                evidence_ids=[eid],
            )
        ],
        actions=[
            dict(
                requirement_id=rid,
                priority="P0",
                horizon="now",
                task="将项目描述拆为数据整理、分析方法和交付物三句。",
                done_when="项目描述清楚呈现个人职责。",
            )
        ],
        suggestions=[
            dict(
                requirement_id=rid,
                original=profile.content.evidence[0].quote,
                revised="整理销售数据并制作分析表，支持月度经营复盘。",
                rationale="突出与岗位相关的工作步骤。",
                evidence_ids=[eid],
                requires_user_input=False,
            )
        ],
    )
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        return (tool_result if native else ok)(payload)

    settings = (
        real_settings(llm_model="deepseek-flash", llm_base_url="https://api.deepseek.com/v1")
        if native
        else real_settings()
    )
    components = build_llm(settings, transport=httpx.MockTransport(handler))
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-09T00:00:00Z"
    )
    frozen = item.score_result.model_dump(mode="json")
    result = asyncio.run(
        ReportService(
            components.gateway, privacy_filter=filter_report_context
        ).generate_enhancement(
            profile, job, item.score_result, metadata, context=TaskContext("real-default")
        )
    )
    assert result.model_dump(mode="json") == payload
    assert len(calls) == 1  # No semantic review request, even for a free rewrite.
    sent_text = json.dumps(calls[0], ensure_ascii=False)
    assert "gap_constraints" not in sent_text
    assert "suggestion_policy" not in sent_text
    task_data = json.loads(calls[0]["messages"][1]["content"].split("\n")[1])
    assert task_data["job_snapshot"]["raw_text"] == job.raw_text

    assert item.score_result.model_dump(mode="json") == frozen
    base = ReportService.build_base_report(profile, job, item.score_result)
    merged = merge_advice(base, result)
    assert merged.summary == payload["summary"]
    assert merged.suggestions[0].revised == payload["suggestions"][0]["revised"]


@pytest.mark.parametrize("bad_reference", ["requirement", "evidence"])
def test_unknown_references_are_rejected_without_interpreting_prose(snapshots, bad_reference):
    profile, job, item = snapshots
    rid = job.content.requirements[0].id
    candidate = ReportContent(
        summary="任意自然语言分析",
        gaps=[],
        actions=[],
        suggestions=[
            dict(
                requirement_id="invented" if bad_reference == "requirement" else rid,
                original=None,
                revised="自由改写",
                rationale="模型解释",
                evidence_ids=["invented"] if bad_reference == "evidence" else [],
                requires_user_input=True,
            )
        ],
    )
    with pytest.raises(ValueError):
        validate_candidate(candidate, profile, job, item.score_result, {rid})


def test_new_analysis_removes_resolved_gaps_only_in_selected_scope(snapshots):
    profile, job, item = snapshots
    base = ReportService.build_base_report(profile, job, item.score_result)
    rid = base.gaps[0].requirement_id
    candidate = ReportContent(
        summary="该项已有足够材料，无需补写。", gaps=[], actions=[], suggestions=[]
    )
    result = merge_advice(base, candidate, [rid])
    assert all(g.requirement_id != rid for g in result.gaps)
    assert result.gaps == [g for g in base.gaps if g.requirement_id != rid]
