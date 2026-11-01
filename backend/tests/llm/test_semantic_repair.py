import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.contracts import DiagnosisItem, Job, Profile
from app.contracts.ports import TaskContext
from app.llm import GatewayError, build_llm
from app.reporting import ReportService
from app.reporting.privacy import filter_report_context
from tests.llm.test_real_gateway import ok, real_settings


@pytest.mark.parametrize("first", ["semantic", "schema", "rate_limit"])
def test_report_validation_repair_shares_one_budget(example, first):
    profile = Profile.model_validate(example("profile.json"))
    job = Job.model_validate(example("job.json"))
    item = DiagnosisItem.model_validate(example("diagnosis-item.json"))
    good = item.report.model_dump(mode="json")
    bad = deepcopy(good)
    bad["suggestions"][0].update(revised="我处理了987654321条记录。", evidence_ids=[])
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1 and first == "rate_limit":
            return httpx.Response(429, json={})
        if len(requests) == 1 and first == "schema":
            return ok({"invalid": "shape"})
        return ok(bad if len(requests) == 1 else good)

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    context = TaskContext("real-default")
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-01T00:00:00Z"
    )
    report = asyncio.run(
        ReportService(components.gateway, privacy_filter=filter_report_context).generate_report(
            profile, job, item.score_result, metadata, context=context
        )
    )
    assert report.model_dump(mode="json") == good
    assert len(requests) == 2 and components.gateway.calls[0].attempts == 2
    if first == "semantic":
        assert "本条 evidence_ids" in requests[1]["messages"][-1]["content"]


@pytest.mark.parametrize("first", ["semantic", "schema", "rate_limit"])
def test_invalid_report_cannot_get_a_third_request(example, first):
    profile = Profile.model_validate(example("profile.json"))
    job = Job.model_validate(example("job.json"))
    item = DiagnosisItem.model_validate(example("diagnosis-item.json"))
    bad = item.report.model_dump(mode="json")
    bad["suggestions"][0].update(revised="我处理了987654321条记录。", evidence_ids=[])
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1 and first == "rate_limit":
            return httpx.Response(429, json={})
        if len(requests) == 1 and first == "schema":
            return ok({"invalid": "shape"})
        return ok(bad)

    components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
    metadata = components.directory.resolve(
        "real-default", "diagnosis_report", "2026-11-01T00:00:00Z"
    )
    frozen = item.score_result.model_dump(mode="json")
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            ReportService(components.gateway, privacy_filter=filter_report_context).generate_report(
                profile, job, item.score_result, metadata, context=TaskContext("real-default")
            )
        )
    assert (
        error.value.code == "MODEL_OUTPUT_INVALID"
        and error.value.reason_code == "UNSUPPORTED_NUMBERS"
    )
    assert len(requests) == 2
    assert item.score_result.model_dump(mode="json") == frozen


def test_semantic_repair_cannot_exceed_input_budget():
    from tests.llm.test_real_gateway import CONTEXT, CUSTOM_SCHEMA, build

    components, stub = build([ok({"ok": True})])

    def invalid(_):
        raise GatewayError(
            "MODEL_OUTPUT_INVALID", "Synthetic rejection", reason_code="UNSUPPORTED_NUMBERS"
        )

    with pytest.raises(GatewayError) as error:
        asyncio.run(
            components.gateway.generate_validated(
                "diagnosis_report",
                {"prompt": "p", "data": "a" * 19999},
                CUSTOM_SCHEMA,
                5,
                context=CONTEXT,
                validate_output=invalid,
            )
        )
    assert len(stub.requests) == 1
    assert error.value.reason_code == "UNSUPPORTED_NUMBERS"
