"""Report fault injection and field/sentence diagnostics; never calls paid APIs."""

import asyncio
import json

import httpx
import pytest

from app.contracts.ports import TaskContext
from app.diagnostics import diagnostic_event
from app.llm import GatewayError, build_llm
from app.llm.openai_compatible import _decode
from app.llm.review import ReviewRejected
from app.platform.errors import task_error
from app.reporting import ReportError, ReportService, validate_report
from app.reporting.explanation import ReportAdvice
from app.reporting.privacy import filter_report_context
from app.scoring import calculate_score
from app.tools.replay_report import replay
from tests.llm.test_real_gateway import ok, real_settings
from tests.reporting.test_grounding import approved_review, review_request


def test_schema_failure_keeps_the_exact_missing_field(snapshots):
    _, _, item = snapshots
    advice = {k: item.report.model_dump(mode="json")[k] for k in ("suggestions", "actions")}
    del advice["suggestions"][0]["revised"]
    with pytest.raises(GatewayError) as caught:
        _decode(json.dumps(advice), ReportAdvice.model_json_schema())
    assert caught.value.issues[0].path == "/suggestions/0/revised"


def test_business_failure_keeps_field_and_offending_sentence(snapshots):
    profile, job, item = snapshots
    report = item.report.model_copy(deep=True)
    report.suggestions[0].revised = "了解 SQL 语法。提高效率 987654321 倍。"
    with pytest.raises(ReportError) as caught:
        validate_report(report, profile.content, job.content, item.score_result)
    issue = caught.value.issues[0]
    assert issue.path == "/suggestions/0/revised" and issue.sentence == 1
    assert report.suggestions[0].revised[issue.start : issue.end] == "提高效率 987654321 倍。"
    assert issue.check == "UNSUPPORTED_NUMBER"


def test_negative_review_localizes_quote_without_logging_text(snapshots):
    profile, job, item = snapshots
    request = review_request(profile, job, item)
    raw = approved_review(request)
    check = next(c for c in raw["checks"] if c["item_id"] == "action:0")
    text = item.report.actions[0].task
    check.update(
        verdict="unsupported", issues=[dict(field="task", quote=text, reason="unsupported_claim")]
    )
    with pytest.raises(ReviewRejected) as caught:
        request.validate_output(raw)
    issue = caught.value.issues[0]
    assert issue.path == "/actions/0/task" and text[issue.start : issue.end] == text
    assert text not in json.dumps(
        diagnostic_event(caught.value, phase="review"), ensure_ascii=False
    )


def setup_v3(
    snapshots, *, target="suggestion:0", malformed=False, generation_bad=False, observer=None
):
    profile, job, item = snapshots
    score = calculate_score(item.score_result.assessments, "coverage-v3")
    advice = {
        "suggestions": [
            {
                **item.report.suggestions[0].model_dump(mode="json"),
                "requires_user_input": False,
                "revised": "了解 SQL 基本语法。",
            }
        ],
        "actions": [a.model_dump(mode="json") for a in item.report.actions],
    }
    if generation_bad:
        advice["suggestions"][0]["revised"] = "提高效率 987654321 倍。"
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return ok(advice)
        sent = json.loads(
            body["messages"][1]["content"].split("任务数据（JSON）：\n", 1)[1].split("\n\n", 1)[0]
        )
        checks = []
        for entry in sent["items"]:
            negative = entry["item_id"] == target
            fields = entry["content"]
            field = (
                "summary"
                if entry["kind"] == "summary"
                else {"gap": "description", "suggestion": "revised", "action": "task"}[
                    entry["kind"]
                ]
            )
            quote = fields if isinstance(fields, str) else fields[field]
            checks.append(
                dict(
                    item_id=entry["item_id"],
                    verdict="unsupported" if negative else "supported",
                    supports=entry["allowed_evidence_ids"] if entry["kind"] == "suggestion" else [],
                    issues=[dict(field=field, quote=quote[:100], reason="unsupported_claim")]
                    if negative
                    else [],
                )
            )
        if malformed:
            checks.pop()
        return ok({"checks": checks, "evidence_checks": None})

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-06T00:00:00Z"
    )
    service = ReportService(
        components.gateway, privacy_filter=filter_report_context, diagnostic_observer=observer
    )
    call = service.generate_report(
        profile, job, score, metadata, context=TaskContext("real-default")
    )
    return call, components.gateway, requests, score


def test_bad_optional_claim_preserves_other_reviewed_content(snapshots, caplog):
    call, gateway, requests, score = setup_v3(snapshots)
    result = asyncio.run(call)
    assert result.suggestions == [] and result.actions and "已略去" in result.summary
    assert len(result.gaps) == sum(a.status != "met" for a in score.assessments)
    assert len(requests) == 2 and gateway.calls[0].attempts == 2
    events = [
        json.loads(r.message.split("report_output_rejected ", 1)[1])
        for r in caplog.records
        if r.message.startswith("report_output_rejected ")
    ]
    event = next(e for e in events if e["phase"] == "review.optional_filtered")
    assert event["issues"][0]["path"] == "/suggestions/0/revised"
    assert "了解 SQL 基本语法" not in json.dumps(event, ensure_ascii=False)


@pytest.mark.parametrize("target", ["summary", "gap:0"])
def test_mandatory_review_failure_rejects_without_retry(snapshots, target):
    call, _, requests, _ = setup_v3(snapshots, target=target)
    with pytest.raises(ReviewRejected) as caught:
        asyncio.run(call)
    assert caught.value.reason_code == "REPORT_GROUNDING_REJECTED" and len(requests) == 2
    assert task_error(caught.value).details["report_trace_id"] == caught.value.report_trace_id


def test_negative_incomplete_review_never_becomes_approval_retry(snapshots):
    call, _, requests, _ = setup_v3(snapshots, malformed=True)
    with pytest.raises(ReviewRejected):
        asyncio.run(call)
    assert len(requests) == 2


def test_bad_optional_numbers_removed_without_regeneration(snapshots, caplog):
    call, _, requests, _ = setup_v3(snapshots, target="none", generation_bad=True)
    result = asyncio.run(call)
    assert result.suggestions == [] and result.actions and len(requests) == 2
    assert "UNSUPPORTED_NUMBER" in caplog.text and "/suggestions/0/revised" in caplog.text
    assert "987654321" not in caplog.text


def test_local_observer_captures_replay_without_logging_prose(snapshots, caplog):
    events = []
    call, _, _, _ = setup_v3(snapshots, observer=events.append)
    asyncio.run(call)
    assert any(e["phase"] == "generation.decoded" for e in events)
    assert any(e["phase"] == "review.response" for e in events)
    assert len({e["trace_id"] for e in events}) == 1
    assert "了解 SQL 基本语法" not in caplog.text


def test_observer_failure_does_not_change_requests(snapshots, caplog):
    def broken(_):
        raise RuntimeError("PRIVATE_RUNTIME_DETAIL")

    call, _, requests, _ = setup_v3(snapshots, observer=broken)
    assert asyncio.run(call).actions and len(requests) == 2
    assert "PRIVATE_RUNTIME_DETAIL" not in caplog.text


def test_offline_results_separate_deterministic_from_semantic(snapshots):
    profile, job, item = snapshots
    candidate = item.report.model_dump(mode="json")
    result = replay(profile, job, item.score_result, candidate)
    assert result["deterministic"] == "PASS" and result["semantic"] == "NOT_RUN"
    candidate["suggestions"][0]["original"] = "非原文敏感测试串"
    result = replay(profile, job, item.score_result, candidate, excerpts=True)
    assert result["issues"][0]["path"] == "/suggestions/0/original"
    assert result["issues"][0]["local_excerpt"] == "非原文敏感测试串"


def test_repeated_audit_quote_does_not_claim_a_unique_sentence():
    from app.diagnostics import locate

    issue = locate(
        ("suggestions", 0, "revised"), "UNSUPPORTED_CLAIM", "重复短句。重复短句。", "重复短句"
    )
    assert issue.occurrences == 2 and issue.start is None and issue.sentence is None


def test_json_syntax_failure_records_character_offset():
    with pytest.raises(GatewayError) as caught:
        _decode('{"suggestions":]', ReportAdvice.model_json_schema())
    assert caught.value.issues[0].check == "JSON_PARSE"
    assert caught.value.issues[0].start == 15


def test_replay_rejects_truncated_but_parseable_provider_envelope(snapshots):
    profile, job, item = snapshots
    value = {
        "choices": [
            {"finish_reason": "length", "message": {"content": item.report.model_dump_json()}}
        ]
    }
    result = replay(profile, job, item.score_result, value)
    assert result["failed_stage"] == "provider_response"
    assert result["reason_code"] == "OUTPUT_TRUNCATED"
    assert result["issues"][0]["path"] == "/choices/0/finish_reason"


def test_malformed_negative_verdict_cannot_trigger_an_approval_retry(snapshots):
    profile, job, item = snapshots
    from app.reporting.grounding import build_grounding_review

    sent = filter_report_context(ReportService._prompt_context(profile, job, item.score_result))
    request = build_grounding_review(
        item.report.model_dump(mode="json"), sent, allow_partial_advice=True
    )
    review = approved_review(request)
    check = next(c for c in review["checks"] if c["item_id"] == "suggestion:0")
    check["verdict"] = "unsupported"
    review["checks"][0]["verdict"] = []
    with pytest.raises(ReviewRejected):
        _decode(json.dumps(review), request.output_schema, request.reject_if_declined)


def test_concurrent_report_trace_ids_are_isolated(snapshots):
    first, second = [], []
    call1, _, _, _ = setup_v3(snapshots, observer=first.append)
    call2, _, _, _ = setup_v3(snapshots, observer=second.append)

    async def run():
        await asyncio.gather(call1, call2)

    asyncio.run(run())
    ids1, ids2 = {e["trace_id"] for e in first}, {e["trace_id"] for e in second}
    assert len(ids1) == len(ids2) == 1 and ids1.isdisjoint(ids2)


def test_private_property_name_is_masked_in_schema_diagnostics():
    from app.diagnostics import field_path

    assert field_path(("suggestions", 0, "private@example.com")) == "/suggestions/0/*"


@pytest.mark.parametrize("fault", ["out_of_scope", "fake_quote", "duplicate", "extra_field"])
def test_declined_optional_items_need_valid_complete_audit_to_be_filtered(snapshots, fault):
    from app.reporting.grounding import build_grounding_review

    profile, job, item = snapshots
    sent = filter_report_context(ReportService._prompt_context(profile, job, item.score_result))
    request = build_grounding_review(
        item.report.model_dump(mode="json"), sent, allow_partial_advice=True
    )
    review = approved_review(request)
    check = next(c for c in review["checks"] if c["item_id"] == "suggestion:0")
    check.update(
        verdict="unsupported",
        supports=[],
        issues=[
            dict(
                field="revised",
                quote=item.report.suggestions[0].revised,
                reason="unsupported_claim",
            )
        ],
    )
    if fault == "out_of_scope":
        check["supports"] = ["not-an-allowed-reference"]
    if fault == "fake_quote":
        check["issues"][0]["quote"] = "不存在的引文"
    if fault == "duplicate":
        review["checks"].append(dict(check))
    if fault == "extra_field":
        check["private_extra"] = "must-not-be-repaired-into-approval"
    with pytest.raises(ReviewRejected):
        request.reject_if_declined(review)
