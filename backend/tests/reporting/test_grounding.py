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
                "supports": deepcopy(item["allowed_evidence_ids"]) if suggestion else [],
            }
        )
    cited = {eid for check in checks for eid in check["supports"]}
    return {
        "checks": checks,
        "evidence_checks": [
            {"evidence_id": eid, "quote": request.prompt_context["evidence"][eid]}
            for eid in sorted(cited)
        ],
    }


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
        check["supports"] = ["e1"]
        review["evidence_checks"] = [
            {"evidence_id": "e1", "quote": profile.content.evidence[0].quote}
        ]
    elif mutation == "invented_quote":
        review["evidence_checks"][0]["quote"] = "熟练操作 Kubernetes。"
    elif mutation == "partial_quote":
        review["evidence_checks"][0]["quote"] = "SQL 基本语法"
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
    assert suggestion["allowed_evidence_ids"] == ["e2"]


def test_review_maps_each_item_to_filtered_frozen_job_requirements(snapshots):
    profile, job, item = snapshots
    job.content.requirements[1].quote += " 联系邮箱：recruiter@example.com。"
    request = review_request(profile, job, item)
    requirements = {r["id"]: r for r in request.prompt_context["frozen_requirements"]}
    assert set(requirements) == {a.requirement_id for a in item.score_result.assessments}
    for entry in request.prompt_context["items"]:
        if entry["kind"] == "summary":
            assert entry["requirement_id"] is None
        else:
            requirement_id = entry["content"]["requirement_id"]
            assert entry["requirement_id"] == requirement_id
            assert requirement_id in requirements
    assert requirements["r2"]["target"] == "SQL"
    assert "recruiter@example.com" not in json.dumps(request.prompt_context, ensure_ascii=False)
    assert "岗位条件不证明候选人具备" in request.prompt_context["prompt"]


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
        assert all(
            request.prompt_context["evidence"][eid] != ignored.quote
            for eid in entry["allowed_evidence_ids"]
        )
        assert entry["requirement_id"] != "ignored-r"


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


def test_review_sees_existing_profile_once_to_catch_false_missing_claim(snapshots):
    from app.llm.gateway import count_input_chars

    profile, job, item = snapshots
    profile.content.overview = "已提供的完整学历信息"
    request = review_request(profile, job, item)
    assert request.prompt_context["profile_overview"] == profile.content.overview
    assert len(request.prompt_context["profile_facts"]) == len(profile.content.facts)
    for entry in request.prompt_context["items"]:
        assert "evidence" not in entry and "requirement" not in entry and "assessment" not in entry
    assert count_input_chars(request.prompt_context) < 20000


def test_review_receives_frozen_cutoff_and_version_specific_suggestion_policy(snapshots):
    profile, job, item = snapshots
    profile.content.as_of_month = "2024-10"
    request = review_request(profile, job, item)
    assert request.prompt_context["profile_as_of_month"] == "2024-10"
    assert request.prompt_context["suggestion_policy"] == "conditional_templates_allowed"
    item.score_result.rule_version = "coverage-v2"
    request = review_request(profile, job, item)
    assert request.prompt_context["suggestion_policy"] == "supported_facts_only"


@pytest.mark.parametrize("violation", ["invented_component", "past_availability"])
def test_scope_and_calendar_rejection_keeps_score_without_reasking(snapshots, violation):
    profile, job, item = snapshots
    profile.content.as_of_month = "2024-10"
    candidate = item.report.model_dump(mode="json")
    if violation == "invented_component":
        job.content.requirements[1].quote = "熟悉设计软件套件。"
        candidate["gaps"][0]["description"] = "必须补齐岗位未列明的排版工具。"
        rejected_item = "gap:0"
    else:
        profile.content.evidence[2].quote = "可到岗时间：2023 年暑期。"
        candidate["actions"][0]["task"] = "确认 2023 年暑期的到岗天数并承诺到岗。"
        rejected_item = "action:0"
    request = review_request(profile, job, item, candidate)
    review = approved_review(request)
    next(check for check in review["checks"] if check["item_id"] == rejected_item)["verdict"] = (
        "unsupported"
    )
    call, gateway, requests = run_reviewed(profile, job, item, candidate, review)
    frozen = item.score_result.model_dump(mode="json")
    with pytest.raises(ReviewRejected):
        asyncio.run(call)
    assert len(requests) == 2 and gateway.calls[0].attempts == 2
    assert item.score_result.model_dump(mode="json") == frozen


def test_many_requirements_share_one_quote_without_expanding_the_review_budget(snapshots):
    from app.contracts import Gap, ReportContent
    from app.llm.openai_compatible import count_input_chars
    from app.platform.validation import validate_job, validate_profile, validate_score
    from app.scoring import ScoringService

    profile, job, item = snapshots
    names = [f"Skill{i}" for i in range(35)]
    quote = "合成技能自述：" + "、".join(names) + "；仅了解基础语法，不代表有项目应用。" * 10
    profile.content.evidence = [profile.content.evidence[1].model_copy(update={"quote": quote})]
    evidence_id = profile.content.evidence[0].id
    profile.content.facts = [
        profile.content.facts[1].model_copy(
            deep=True,
            update={
                "id": f"f{i}",
                "label": name,
                "evidence_ids": [evidence_id],
                "application": "claimed",
            },
        )
        for i, name in enumerate(names)
    ]
    job.content.requirements = [
        job.content.requirements[1].model_copy(
            deep=True,
            update={
                "id": f"r{i}",
                "target": name,
                "quote": f"要求掌握{name}",
            },
        )
        for i, name in enumerate(names)
    ]
    validate_profile(profile.content, profile.content.as_of_month)
    validate_job(job.content, "；".join(r.quote for r in job.content.requirements))
    scorer = ScoringService()
    score = scorer.calculate_score(
        scorer.assess_requirements(profile.content, job.content, "matcher-v1"), "coverage-v1"
    )
    validate_score(score, profile.content, job.content)
    report = ReportContent(
        summary="技能仅有自述，需核实应用情况。",
        suggestions=[],
        actions=[],
        gaps=[
            Gap(
                requirement_id=a.requirement_id,
                kind="partial_gap",
                description="请核实实际应用场景。",
                evidence_ids=a.evidence_ids,
            )
            for a in score.assessments
        ],
    )
    validate_report(report, profile.content, job.content, score)
    sent = filter_report_context(ReportService._prompt_context(profile, job, score))
    request = build_grounding_review(report.model_dump(mode="json"), sent)
    assert count_input_chars(sent) < 20000
    assert count_input_chars(request.prompt_context) < 20000
    expanded = deepcopy(request.prompt_context)
    table = expanded.pop("evidence")
    for entry in expanded["items"]:
        entry["allowed_evidence"] = [
            {"evidence_id": eid, "quote": table[eid]} for eid in entry.pop("allowed_evidence_ids")
        ]
    assert count_input_chars(expanded) > 20000
    serialized = json.dumps(request.prompt_context, ensure_ascii=False)
    assert serialized.count(quote) == 1
    review = approved_review(request)
    for check in review["checks"]:
        check["supports"] = [evidence_id]
    review["evidence_checks"] = [{"evidence_id": evidence_id, "quote": quote}]
    request.validate_output(review)
    assert json.dumps(review, ensure_ascii=False).count(quote) == 1
    assert 8192 <= request.max_output_tokens <= 16384
