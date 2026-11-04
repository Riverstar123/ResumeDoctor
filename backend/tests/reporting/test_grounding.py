"""Scoped, independent report review; HTTP responses are controlled synthetic fixtures.

These tests establish rejection/acceptance and evidence boundaries, not real-model
semantic accuracy. The semantic verdict itself must also be evaluated with providers.
"""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.contracts import ReportContent
from app.contracts.ports import TaskContext
from app.llm import GatewayError, build_llm
from app.llm.review import ReviewRejected
from app.reporting import ReportError, ReportService, validate_report
from app.reporting.grounding import build_grounding_review
from app.reporting.privacy import filter_report_context
from tests.llm.test_real_gateway import ok, real_settings


def approved_review(request):
    """A scripted reviewer fixture, never a fake semantic entailment algorithm."""
    checks = []
    for item in request.prompt_context["items"]:
        suggestion = item["kind"] == "suggestion"
        verdict = "supported"
        if suggestion and item["content"]["requires_user_input"]:
            verdict = "conditional_template"
        checks.append(
            {
                "item_id": item["item_id"],
                "verdict": verdict,
                "supports": deepcopy(item["allowed_evidence"]) if suggestion else [],
            }
        )
    return {"checks": checks}


def review_request(profile, job, item, candidate=None):
    return build_grounding_review(
        candidate or item.report.model_dump(mode="json"),
        filter_report_context(ReportService._prompt_context(profile, job, item.score_result)),
    )


def run_reviewed(profile, job, item, candidate, review, responses=None):
    requests = []
    queue = list(responses or [ok(candidate), ok(review)])

    async def handler(request):
        requests.append(json.loads(request.content))
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        return response

    async def no_sleep(_):
        pass

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    components.gateway._sleep = no_sleep
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-05T00:00:00Z"
    )
    service = ReportService(components.gateway, privacy_filter=filter_report_context)
    call = service.generate_report(
        profile, job, item.score_result, metadata, context=TaskContext("real-default")
    )
    return call, components.gateway, requests


def test_legal_paraphrase_is_returned_only_after_scoped_review(snapshots):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    candidate["suggestions"][0].update(revised="SQL：了解基本语法。", requires_user_input=False)
    request = review_request(profile, job, item, candidate)
    call, gateway, requests = run_reviewed(profile, job, item, candidate, approved_review(request))
    frozen = item.score_result.model_dump(mode="json")
    result = asyncio.run(call)
    assert result.model_dump(mode="json") == candidate
    assert item.score_result.model_dump(mode="json") == frozen
    assert len(requests) == 2 and gateway.calls[0].attempts == 2
    assert requests[0]["model"] == requests[1]["model"]
    assert "独立" in requests[1]["messages"][0]["content"]
    assert len(gateway.calls) == 1 and gateway.calls[0].outcome == "ok"


@pytest.mark.parametrize(
    ("source", "revised", "verdict"),
    [
        ("了解 SQL 基本语法。", "负责 Kubernetes 集群部署。", "unsupported"),
        ("协助团队整理 SQL 查询。", "独立主导 SQL 数据平台建设。", "unsupported"),
        ("没有使用 SQL 完成项目。", "使用 SQL 完成项目。", "contradicted"),
        ("了解 SQL 基本语法。", "熟练设计数据库架构。", "uncertain"),
    ],
)
def test_unsupported_semantics_fail_closed_without_reasking_reviewer(
    snapshots, source, revised, verdict
):
    profile, job, item = snapshots
    profile.content.evidence[1].quote = source
    candidate = item.report.model_dump(mode="json")
    candidate["suggestions"][0].update(original=source, revised=revised, requires_user_input=False)
    request = review_request(profile, job, item, candidate)
    review = approved_review(request)
    next(check for check in review["checks"] if check["item_id"] == "suggestion:0")["verdict"] = (
        verdict
    )
    call, gateway, requests = run_reviewed(profile, job, item, candidate, review)
    frozen = item.score_result.model_dump(mode="json")
    with pytest.raises(ReviewRejected):
        asyncio.run(call)
    assert len(requests) == 2  # no third request asking the reviewer to change its mind
    assert gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"
    assert item.score_result.model_dump(mode="json") == frozen


def test_unknown_must_not_become_a_claim_that_the_user_lacks_the_skill(snapshots):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    candidate["gaps"][1]["description"] = "用户不会 Docker。"
    review = approved_review(review_request(profile, job, item, candidate))
    next(check for check in review["checks"] if check["item_id"] == "gap:1")["verdict"] = (
        "unsupported"
    )
    call, _, requests = run_reviewed(profile, job, item, candidate, review)
    with pytest.raises(ReviewRejected):
        asyncio.run(call)
    assert len(requests) == 2
    assert item.score_result.assessments[2].status == "unknown"


def test_negative_verdict_cannot_be_repaired_away_using_a_schema_error(snapshots):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    review = approved_review(review_request(profile, job, item, candidate))
    review["checks"][0].update(verdict="unsupported", extra="invalid schema")
    call, gateway, requests = run_reviewed(profile, job, item, candidate, review)
    with pytest.raises(ReviewRejected):
        asyncio.run(call)
    assert len(requests) == 2 and gateway.calls[0].attempts == 2


@pytest.mark.parametrize(
    "mutation",
    ["foreign_id", "invented_quote", "partial_quote", "missing", "duplicate", "empty_support"],
)
def test_review_cannot_self_certify_invalid_references_or_coverage(snapshots, mutation):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    candidate["suggestions"][0].update(revised="SQL：了解基本语法。", requires_user_input=False)
    request = review_request(profile, job, item, candidate)
    review = approved_review(request)
    check = next(check for check in review["checks"] if check["item_id"] == "suggestion:0")
    if mutation == "foreign_id":
        check["supports"] = [{"evidence_id": "e1", "quote": profile.content.evidence[0].quote}]
    elif mutation == "invented_quote":
        check["supports"][0]["quote"] = "熟练操作 Kubernetes。"
    elif mutation == "partial_quote":
        check["supports"][0]["quote"] = "SQL 基本语法"
    elif mutation == "missing":
        review["checks"].remove(check)
    elif mutation == "duplicate":
        review["checks"].append(deepcopy(check))
    else:
        check["supports"] = []
    with pytest.raises(ReviewRejected):
        request.validate_output(review)


def test_original_must_belong_to_this_suggestions_cited_evidence(snapshots):
    profile, job, item = snapshots
    report = item.report.model_copy(deep=True)
    report.suggestions[0].original = profile.content.evidence[0].quote
    with pytest.raises(ReportError, match="本条引用"):
        validate_report(report, profile.content, job.content, item.score_result)


def test_conditional_template_cannot_approve_an_unmarked_completed_draft(snapshots):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    candidate["suggestions"][0].update(revised="负责 Kubernetes 部署。", requires_user_input=False)
    request = review_request(profile, job, item, candidate)
    review = approved_review(request)
    next(check for check in review["checks"] if check["item_id"] == "suggestion:0")["verdict"] = (
        "conditional_template"
    )
    with pytest.raises(ReviewRejected):
        request.validate_output(review)


def test_conditional_template_can_preserve_missing_facts_as_placeholders(snapshots):
    profile, job, item = snapshots
    request = review_request(profile, job, item)
    request.validate_output(approved_review(request))


def test_review_never_receives_raw_contacts_or_out_of_scope_suggestion_evidence(snapshots):
    profile, job, item = snapshots
    profile.content.overview = "电话：13800138000，邮箱 student@example.com。"
    profile.content.evidence[1].quote += " 邮箱：student@example.com。"
    request = review_request(profile, job, item)
    text = json.dumps(request.prompt_context, ensure_ascii=False)
    assert "13800138000" not in text and "student@example.com" not in text
    suggestion = next(i for i in request.prompt_context["items"] if i["item_id"] == "suggestion:0")
    assert [e["evidence_id"] for e in suggestion["allowed_evidence"]] == ["e2"]


def test_review_maps_each_item_to_filtered_frozen_job_requirements(snapshots):
    profile, job, item = snapshots
    job.content.requirements[1].quote += " 联系邮箱：recruiter@example.com。"
    request = review_request(profile, job, item)
    requirements = {r["id"]: r for r in request.prompt_context["frozen_requirements"]}
    assert set(requirements) == {a.requirement_id for a in item.score_result.assessments}
    for entry in request.prompt_context["items"]:
        if entry["kind"] == "summary":
            assert entry["requirement"] is None
        else:
            requirement_id = entry["content"]["requirement_id"]
            assert entry["requirement"] == requirements[requirement_id]
            assert entry["assessment"]["requirement_id"] == requirement_id
    assert requirements["r2"]["target"] == "SQL"
    assert "recruiter@example.com" not in json.dumps(request.prompt_context, ensure_ascii=False)
    assert "不证明候选人具备" in request.prompt_context["prompt"]


def test_review_omits_ignored_requirements_and_does_not_treat_jd_as_evidence(snapshots):
    profile, job, item = snapshots
    ignored = job.content.requirements[1].model_copy(
        deep=True,
        update={
            "id": "ignored-r",
            "ignored": True,
            "ignore_reason": "不计分条件",
            "quote": "仅作为背景，不作为候选人要求。",
            "target": "ignored-skill",
        },
    )
    job.content.requirements.append(ignored)
    request = review_request(profile, job, item)
    assert "ignored-r" not in {r["id"] for r in request.prompt_context["frozen_requirements"]}
    for entry in request.prompt_context["items"]:
        assert all(evidence["quote"] != ignored.quote for evidence in entry["allowed_evidence"])
        if entry["requirement"] is not None:
            assert entry["requirement"]["id"] != "ignored-r"


def test_non_fake_gateway_without_independent_review_fails_before_a_provider_call(snapshots):
    profile, job, item = snapshots

    class LegacyGateway:
        is_fake = False

        async def generate_structured(self, *args, **kwargs):
            pytest.fail("an unreviewable real report must not be generated")

    with pytest.raises(ReportError, match="独立事实核对"):
        asyncio.run(
            ReportService(LegacyGateway(), privacy_filter=filter_report_context).generate_report(
                profile,
                job,
                item.score_result,
                item.model_metadata,
                context=TaskContext(item.model_metadata.model_id),
            )
        )


def test_fake_flag_cannot_bypass_review_for_a_frozen_real_provider(snapshots):
    profile, job, item = snapshots

    class DisguisedFakeGateway:
        is_fake = True

        async def generate_structured(self, *args, **kwargs):
            pytest.fail("real frozen metadata must never use the synthetic exemption")

    metadata = item.model_metadata.model_copy(update={"provider": "real-provider"})
    with pytest.raises(ReportError, match="独立事实核对"):
        asyncio.run(
            ReportService(DisguisedFakeGateway()).generate_report(
                profile,
                job,
                item.score_result,
                metadata,
                context=TaskContext(metadata.model_id),
            )
        )


def test_unsupported_numeric_claim_is_rejected_before_semantic_review(snapshots):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    candidate["suggestions"][0]["revised"] = "将处理效率提高了 99%。"
    call, gateway, requests = run_reviewed(profile, job, item, candidate, {}, [ok(candidate)])
    with pytest.raises(GatewayError) as error:
        asyncio.run(call)
    assert error.value.reason_code == "UNSUPPORTED_NUMBERS"
    assert len(requests) == 2 and gateway.calls[0].attempts == 2


def test_model_report_schema_remains_the_public_report_content(snapshots):
    profile, job, item = snapshots
    request = review_request(profile, job, item)
    assert "checks" in request.output_schema["properties"]
    assert "checks" not in ReportContent.model_json_schema()["properties"]
