"""M2 preserves public module codes, never exception text or provider details."""

import asyncio
from uuid import uuid4

import pytest

from app.contracts import ErrorInfo
from app.intake import IntakeError
from app.llm import GatewayError
from app.platform.errors import PlatformError
from app.platform.fakes import FakeIntake, FakeReporting
from app.platform.service import task_error
from app.scoring.errors import ScoringError

from .test_api import JOB, app_for, check, clients, graph, poll, post, session

PRIVATE = "synthetic-provider-token /private/resume-path https://provider.invalid/private"


class ReportFailure(ValueError):
    """RP-01 ReportError's code/message port shape, without importing unmerged #52."""

    def __init__(self, code, message=PRIVATE):
        self.code = code
        super().__init__(message)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (GatewayError(code, PRIVATE), code)
        for code in (
            "MODEL_TIMEOUT",
            "MODEL_OUTPUT_INVALID",
            "PROVIDER_UNAVAILABLE",
            "MODEL_UNAVAILABLE",
            "INPUT_TOO_LONG",
        )
    ]
    + [
        (IntakeError("NO_TEXT_LAYER", PRIVATE), "NO_TEXT_LAYER"),
        (IntakeError("FILE_TOO_LARGE", PRIVATE), "FILE_TOO_LARGE"),
        (IntakeError("UNSUPPORTED_FILE_TYPE", PRIVATE), "UNSUPPORTED_FILE_TYPE"),
        (IntakeError("DOCUMENT_PARSE_FAILED", PRIVATE), "DOCUMENT_PARSE_FAILED"),
        (IntakeError("VALIDATION_ERROR", PRIVATE), "VALIDATION_ERROR"),
        (ScoringError("NO_SCORABLE_REQUIREMENTS", PRIVATE), "NO_SCORABLE_REQUIREMENTS"),
        (ReportFailure("MODEL_OUTPUT_INVALID"), "MODEL_OUTPUT_INVALID"),
        (PlatformError(409, "VERSION_CONFLICT", PRIVATE), "VERSION_CONFLICT"),
        (TimeoutError(PRIVATE), "TASK_TIMEOUT"),
    ],
)
def test_known_module_codes_are_preserved_and_messages_are_redacted(error, code):
    result = task_error(error)
    assert result.code == code
    assert result.message
    assert result.details == {}
    for private in PRIVATE.split():
        assert private not in result.model_dump_json()


@pytest.mark.parametrize("code", ["PRIVACY_FILTER_REQUIRED", PRIVATE, None, 17, [], {}])
def test_unknown_or_invalid_module_codes_fail_closed(code):
    result = task_error(ReportFailure(code))
    assert result.code == "INTERNAL_ERROR"
    assert "synthetic-provider-token" not in result.model_dump_json()


def test_stored_error_info_is_resanitized():
    error = ErrorInfo(code="MODEL_TIMEOUT", message=PRIVATE, details={"input": PRIVATE})
    result = task_error(error)
    assert result.code == "MODEL_TIMEOUT"
    assert result.details == {}
    assert "synthetic-provider-token" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (GatewayError("MODEL_TIMEOUT", PRIVATE), "MODEL_TIMEOUT"),
        (GatewayError("INPUT_TOO_LONG", PRIVATE), "INPUT_TOO_LONG"),
        (IntakeError("VALIDATION_ERROR", PRIVATE), "VALIDATION_ERROR"),
        (ReportFailure(PRIVATE), "INTERNAL_ERROR"),
    ],
)
def test_failed_job_task_exposes_safe_module_code(error, code, caplog):
    class BrokenIntake(FakeIntake):
        async def extract_job(self, *args, **kwargs):
            raise error

    async def run():
        app = app_for(intake=BrokenIntake())
        async with clients(app) as (client,):
            await session(client)
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["result"] is None
            assert task["error"]["code"] == code
            assert "synthetic-provider-token" not in str(task)
            assert not app.state.platform.repo.jobs

    asyncio.run(run())
    assert "synthetic-provider-token" not in caplog.text


@pytest.mark.parametrize("code", ["NO_TEXT_LAYER", "DOCUMENT_PARSE_FAILED"])
def test_document_module_error_is_visible_on_task(code):
    class BrokenIntake(FakeIntake):
        async def extract_document(self, *args, **kwargs):
            raise IntakeError(code, PRIVATE)

    async def run():
        app = app_for(intake=BrokenIntake())
        async with clients(app) as (client,):
            await session(client)
            response = await client.post(
                "/api/v1/documents",
                data={"model_id": "demo-model-a"},
                files={"file": ("synthetic.pdf", b"%PDF-1.7\n% stub", "application/pdf")},
                headers={"Idempotency-Key": str(uuid4())},
            )
            accepted = check(response, 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["error"]["code"] == code
            assert "synthetic-provider-token" not in str(task)
            assert not app.state.platform.repo.profiles

    asyncio.run(run())


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (GatewayError("MODEL_TIMEOUT", PRIVATE), "MODEL_TIMEOUT"),
        (ReportFailure("MODEL_OUTPUT_INVALID"), "MODEL_OUTPUT_INVALID"),
    ],
)
def test_report_module_failure_preserves_score_and_export(error, code, caplog):
    class BrokenReporting(FakeReporting):
        async def generate_report(self, *args, **kwargs):
            raise error

    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            baseline = await graph(client)
            app.state.platform.reporting = BrokenReporting()
            accepted = check(
                await post(client, "/api/v1/diagnoses", baseline["body"]),
                202,
                "DiagnosisAccepted",
            )
            task, _ = await poll(client, accepted["task_id"])
            diagnosis = check(
                await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}"), 200, "Diagnosis"
            )
            item = diagnosis["items"][0]
            assert task["status"] == diagnosis["status"] == "partial"
            assert item["status"] == "score_only" and item["report"] is None
            assert item["score_result"] == baseline["diagnosis"]["items"][0]["score_result"]
            assert item["error"]["code"] == code
            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert exported.status_code == 200 and code in exported.text
            assert "synthetic-provider-token" not in str(diagnosis) + exported.text

    asyncio.run(run())
    assert "synthetic-provider-token" not in caplog.text
