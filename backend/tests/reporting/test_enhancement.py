"""Synthetic local replay of independent base reports and bounded enhancement."""

import asyncio
import json

import httpx
import pytest

from app.contracts.ports import TaskContext
from app.llm import GatewayError, build_llm
from app.reporting import ReportError, ReportService
from app.reporting.enhancement import candidate_id
from app.reporting.grounding import build_grounding_review
from app.reporting.privacy import filter_report_context
from tests.llm.test_real_gateway import ok, real_settings
from tests.reporting.test_grounding import approved_review


def run_plan(snapshots, choices, *, reject=False, malformed=False, selected=None, native=False):
    profile, job, item = snapshots
    requests = []
    from tests.llm.test_structured_output import tool_result

    response = tool_result if native else ok

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return response({"choices": choices})
        sent, _ = json.JSONDecoder().raw_decode(
            body["messages"][1]["content"].split("任务数据（JSON）：\n", 1)[1]
        )
        assert all(e["kind"] == "suggestion" for e in sent["items"])
        checks = [
            dict(
                item_id=e["item_id"],
                verdict="unsupported" if reject else "supported",
                supports=e["allowed_evidence_ids"],
                issues=[],
            )
            for e in sent["items"]
        ]
        return response({"checks": [] if malformed else checks, "evidence_checks": None})

    settings = (
        real_settings(llm_model="deepseek-flash", llm_base_url="https://api.deepseek.com/v1")
        if native
        else real_settings()
    )
    components = build_llm(settings, transport=httpx.MockTransport(handler))
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-07T00:00:00Z"
    )
    service = ReportService(components.gateway, privacy_filter=filter_report_context)
    call = service.generate_enhancement(
        profile,
        job,
        item.score_result,
        metadata,
        context=TaskContext("real-default"),
        requirement_ids=selected,
    )
    return call, requests, service


def matching_choice(snapshots, operation="highlight_evidence"):
    profile, _, item = snapshots
    for a in item.score_result.assessments:
        for f in profile.content.facts:
            if f.polarity == "positive" and set(f.evidence_ids) & set(a.evidence_ids):
                e = next(e for e in profile.content.evidence if e.id == f.evidence_ids[0])
                return dict(
                    operation=operation,
                    requirement_id=a.requirement_id,
                    fact_ids=[f.id],
                    rewritten=e.quote if operation == "rewrite" else None,
                )
    raise AssertionError("fixture needs positive evidence")


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


@pytest.mark.parametrize("native", [False, True])
def test_controlled_plan_skips_semantic_review(snapshots, native):
    call, requests, service = run_plan(snapshots, [matching_choice(snapshots)], native=native)
    report = asyncio.run(call)
    base = service.build_base_report(snapshots[0], snapshots[1], snapshots[2].score_result)
    assert len(requests) == 1 and report.actions and not report.suggestions
    assert report.summary == base.summary and report.gaps == base.gaps
    assert report.omitted_count == 0 and "omitted_count" not in report.model_dump()


@pytest.mark.parametrize(
    "change", ["invented_fact", "free_controlled_text", "wrong_requirement", "negative_fact"]
)
def test_illegal_controlled_operations_are_not_rendered(snapshots, change):
    choice = matching_choice(snapshots)
    if change == "invented_fact":
        choice["fact_ids"] = ["invented"]
    elif change == "free_controlled_text":
        choice["rewritten"] = "独立负责并实现效率提升"
    elif change == "wrong_requirement":
        choice["requirement_id"] = "not-scored"
    else:
        next(
            f for f in snapshots[0].content.facts if f.id == choice["fact_ids"][0]
        ).polarity = "negative"
    call, requests, _ = run_plan(snapshots, [choice])
    report = asyncio.run(call)
    assert report.suggestions == report.actions == [] and report.omitted_count == 1
    assert len(requests) == 1


@pytest.mark.parametrize("native", [False, True])
def test_free_rewrite_review_only_receives_optional_items(snapshots, native):
    call, requests, service = run_plan(
        snapshots, [matching_choice(snapshots, "rewrite")], native=native
    )
    report = asyncio.run(call)
    base = service.build_base_report(snapshots[0], snapshots[1], snapshots[2].score_result)
    assert len(requests) == 2 and report.suggestions
    assert report.summary == base.summary and report.gaps == base.gaps


def test_rejected_rewrite_keeps_controlled_actions_and_base(snapshots):
    call, requests, service = run_plan(
        snapshots, [matching_choice(snapshots), matching_choice(snapshots, "rewrite")], reject=True
    )
    report = asyncio.run(call)
    base = service.build_base_report(snapshots[0], snapshots[1], snapshots[2].score_result)
    assert len(requests) == 2 and report.actions and not report.suggestions
    assert report.summary == base.summary and report.gaps == base.gaps and report.omitted_count == 1


def test_incomplete_review_fails_enhancement_without_retry(snapshots):
    call, requests, service = run_plan(
        snapshots, [matching_choice(snapshots, "rewrite")], malformed=True
    )
    with pytest.raises(GatewayError):
        asyncio.run(call)
    assert len(requests) == 2
    assert service.build_base_report(snapshots[0], snapshots[1], snapshots[2].score_result).summary


def test_selected_requirement_scope_is_enforced_locally(snapshots):
    choice = matching_choice(snapshots)
    other = next(
        a.requirement_id
        for a in snapshots[2].score_result.assessments
        if a.requirement_id != choice["requirement_id"]
    )
    call, requests, _ = run_plan(snapshots, [choice], selected=[other])
    report = asyncio.run(call)
    assert report.actions == report.suggestions == [] and report.omitted_count == 1
    sent = json.loads(
        requests[0]["messages"][1]["content"]
        .split("任务数据（JSON）：\n", 1)[1]
        .split("\n\n", 1)[0]
    )
    assert sent["selected_requirement_ids"] == [other]
    assert len(sent["profile_snapshot"]["content"]["evidence"]) == len(
        snapshots[0].content.evidence
    )


def test_review_ids_are_content_bound(snapshots):
    profile, job, item = snapshots
    sent = filter_report_context(ReportService._prompt_context(profile, job, item.score_result))
    request = build_grounding_review(
        item.report.model_dump(mode="json"), sent, advice_only=True, allow_partial_advice=True
    )
    for entry in request.prompt_context["items"]:
        assert entry["item_id"] == candidate_id(entry["kind"], entry["content"])
    request.validate_output(approved_review(request))


def test_controlled_review_is_available_only_for_unknown_requirements(snapshots):
    unknown = next(a for a in snapshots[2].score_result.assessments if a.status == "unknown")
    choices = [
        dict(
            operation="review_requirement",
            requirement_id=unknown.requirement_id,
            fact_ids=[],
            rewritten=None,
        )
    ]
    call, requests, _ = run_plan(snapshots, choices)
    report = asyncio.run(call)
    assert len(requests) == 1 and report.actions
    assert "缺少" not in report.actions[0].task
    choices[0]["requirement_id"] = matching_choice(snapshots)["requirement_id"]
    call, requests, _ = run_plan(snapshots, choices)
    report = asyncio.run(call)
    assert not report.actions and report.omitted_count == 1


def test_conflicting_assessment_cannot_receive_unreviewed_highlight(snapshots):
    choice = matching_choice(snapshots)
    assessment = next(
        a
        for a in snapshots[2].score_result.assessments
        if a.requirement_id == choice["requirement_id"]
    )
    assessment.status = "unknown"
    assessment.unknown_reason = "conflicting_evidence"
    call, requests, _ = run_plan(snapshots, [choice])
    report = asyncio.run(call)
    assert not report.actions and report.omitted_count == 1 and len(requests) == 1


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


@pytest.mark.parametrize("operation", ["highlight_evidence", "rewrite"])
def test_presented_quote_is_bound_to_requirement_not_first_fact_reference(snapshots, operation):
    from app.platform.validation import validate_profile

    profile, _, item = snapshots
    choice = matching_choice(snapshots, operation)
    fact = next(f for f in profile.content.facts if f.id == choice["fact_ids"][0])
    assessment = next(
        a for a in item.score_result.assessments if a.requirement_id == choice["requirement_id"]
    )
    unrelated = next(e for e in profile.content.evidence if e.id not in assessment.evidence_ids)
    source = next(e for e in profile.content.evidence if e.id == fact.evidence_ids[0])
    fact.evidence_ids.insert(0, unrelated.id)
    validate_profile(profile.content, "2026-11")
    call, requests, _ = run_plan(snapshots, [choice])
    report = asyncio.run(call)
    if operation == "highlight_evidence":
        assert source.quote in report.actions[0].task
        assert unrelated.quote not in report.actions[0].task
        assert len(requests) == 1
    else:
        assert report.suggestions[0].original == source.quote
        assert set(report.suggestions[0].evidence_ids) == set(fact.evidence_ids)
        review, _ = json.JSONDecoder().raw_decode(
            requests[1]["messages"][1]["content"].split("任务数据（JSON）：\n", 1)[1]
        )
        assert unrelated.id in review["items"][0]["allowed_evidence_ids"]
        assert source.id in review["items"][0]["allowed_evidence_ids"]
        assert len(requests) == 2
    assert report.omitted_count == 0


@pytest.mark.parametrize("quote", ["", "[联系方式已过滤]"])
def test_unusable_intersection_is_omitted_without_dropping_another_item(snapshots, quote):
    from app.reporting.enhancement import render_plan

    profile, job, item = snapshots
    choice = matching_choice(snapshots)
    fact = next(f for f in profile.content.facts if f.id == choice["fact_ids"][0])
    assessment = next(
        a for a in item.score_result.assessments if a.requirement_id == choice["requirement_id"]
    )
    unrelated = next(e for e in profile.content.evidence if e.id not in assessment.evidence_ids)
    fact.evidence_ids.insert(0, unrelated.id)
    sent = filter_report_context(ReportService._prompt_context(profile, job, item.score_result))
    for evidence in sent["profile_snapshot"]["content"]["evidence"]:
        if evidence["id"] in assessment.evidence_ids:
            evidence["quote"] = quote
    unknown = next(a for a in item.score_result.assessments if a.status == "unknown")
    other = dict(
        operation="review_requirement",
        requirement_id=unknown.requirement_id,
        fact_ids=[],
        rewritten=None,
    )
    report, omitted = render_plan(
        {"choices": [choice, other]}, sent, {choice["requirement_id"], unknown.requirement_id}
    )
    assert omitted == 1 and len(report["actions"]) == 1 and not report["suggestions"]
    assert report["actions"][0]["requirement_id"] == unknown.requirement_id
    assert unrelated.quote not in report["actions"][0]["task"]
