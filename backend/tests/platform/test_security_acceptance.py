"""QA-02 security checks across HTTP, real M3 parsing and durable PostgreSQL work.

The imported fixtures require a migrated, explicitly named test PostgreSQL database.
Only document bytes generated at runtime and an in-process synthetic model are used.
These tests verify system boundaries, not the injection resistance of a real LLM.
"""

# ruff: noqa: F811 -- imported PostgreSQL fixtures are injected by pytest.

import asyncio
import logging
from copy import deepcopy
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import text  # noqa: E402

from app.database import create_app  # noqa: E402
from app.intake import GatewayIntake  # noqa: E402
from app.intake.documents import DOCX, PDF  # noqa: E402
from app.llm import FakeModelDirectory, FakeModelGateway, GatewayError  # noqa: E402
from app.platform.integration import GatewayCatalog  # noqa: E402
from app.platform.jobs.store import JobStore  # noqa: E402
from app.platform.jobs.worker import Worker  # noqa: E402
from app.reporting import ReportService  # noqa: E402
from app.scoring import ScoringService  # noqa: E402
from app.settings import Settings  # noqa: E402
from tests.intake.document_fixtures import docx_bytes, pdf_bytes  # noqa: E402

from .test_api import check, clients, post, session  # noqa: E402
from .test_postgres import (  # noqa: E402
    counts,
    engine,  # noqa: F401
    job_content,
    repo,  # noqa: F401
    upload_dir,  # noqa: F401
)

PRIVATE_RESUME = "qa25-synthetic-private-resume"
PRIVATE_FAILURE = "qa25-synthetic-api-key /qa25/private/file qa25-provider.invalid"
DOCUMENT_TEXT = f"使用 Python 完成课程数据清洗项目。\n{PRIVATE_RESUME}"
SOURCE_QUOTE = "使用 Python 完成课程数据清洗项目。"


class ControlledGateway(FakeModelGateway):
    """Controlled model output; parsing, validation, scoring and storage stay real."""

    def __init__(self, directory, *, pause=False, fail_profile=False):
        super().__init__(directory)
        self.pause, self.fail_profile = pause, fail_profile
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.returned = False

    async def _produce(self, task_name, prompt_context, behavior):
        if task_name == "profile_extract":
            self.entered.set()
            if self.pause:
                await self.release.wait()
            if self.fail_profile:
                raise GatewayError("MODEL_OUTPUT_INVALID", PRIVATE_FAILURE)
            self.returned = True
            return {
                "overview": PRIVATE_RESUME,
                "as_of_month": "2026-09",
                "facts": [
                    {
                        "id": "f1",
                        "kind": "project",
                        "label": "Python",
                        "value": None,
                        "polarity": "positive",
                        "application": "applied",
                        "start_month": None,
                        "end_month": None,
                        "completed": None,
                        "evidence_ids": ["e1"],
                    }
                ],
                "evidence": [
                    {
                        "id": "e1",
                        "source_type": prompt_context["source_type"],
                        "source_id": prompt_context["source_id"],
                        "quote": SOURCE_QUOTE,
                        "locator": None,
                    }
                ],
            }
        if task_name == "job_extract":
            return job_content().model_dump(mode="json")
        return await super()._produce(task_name, prompt_context, behavior)


class ObservedIntake(GatewayIntake):
    def __init__(self, gateway):
        super().__init__(gateway)
        self.handles = []
        self.parsed = []

    async def extract_document(self, handle, media_type):
        self.handles.append(handle)
        result = await super().extract_document(handle, media_type)
        self.parsed.append(result)
        return result


def assembly(repo, upload_dir, *, gateway_options=None):
    directory = FakeModelDirectory()
    gateway = ControlledGateway(directory, **(gateway_options or {}))
    intake = ObservedIntake(gateway)
    catalog = GatewayCatalog(directory)
    reporting = ReportService(gateway)
    app = create_app(
        Settings(_env_file=None, upload_dir=upload_dir), repository=repo, catalog=catalog
    )
    app.state.platform.reporting = reporting
    worker = Worker(
        JobStore(repo),
        intake=intake,
        scoring=ScoringService(),
        reporting=reporting,
        catalog=catalog,
        upload_dir=upload_dir,
    )
    return app, worker, intake, gateway


async def upload(client, data, media_type=PDF):
    # The original name is untrusted and must not become a filesystem path.
    return check(
        await client.post(
            "/api/v1/documents",
            data={"model_id": "demo-model-a"},
            files={"file": ("../../qa25-untrusted-name.pdf", data, media_type)},
            headers={"Idempotency-Key": uuid4().hex},
        ),
        202,
        "TaskAccepted",
    )


async def task_result(client, task_id, *, status):
    result = check(await client.get(f"/api/v1/tasks/{task_id}"), 200, "Task")
    assert result["status"] == status, result
    return result


def document_rows(engine, sid):
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT id, storage_key, status FROM documents WHERE session_id=:sid"),
                {"sid": sid},
            )
            .mappings()
            .all()
        )


def assert_cleanup_complete(engine, upload_dir, keys):
    assert all(not (upload_dir / key).exists() for key in keys)
    with engine.connect() as connection:
        for key in keys:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM file_cleanup WHERE storage_key=:key"),
                    {"key": key},
                )
                == 0
            )


@pytest.mark.parametrize(
    "case,code",
    [
        ("corrupt-pdf", "DOCUMENT_PARSE_FAILED"),
        ("image-only-pdf", "NO_TEXT_LAYER"),
        ("over-page-limit", "DOCUMENT_PARSE_FAILED"),
        ("docx-traversal", "DOCUMENT_PARSE_FAILED"),
    ],
)
def test_t02_http_to_real_parser_fails_closed_and_releases_original(
    repo, engine, upload_dir, caplog, case, code
):
    caplog.set_level(logging.DEBUG, logger="app")

    async def run():
        app, worker, intake, gateway = assembly(repo, upload_dir)
        async with clients(app) as (client,):
            sid = (await session(client))["id"]
            data, media = {
                "corrupt-pdf": (b"%PDF-1.7\n" + PRIVATE_RESUME.encode(), PDF),
                "image-only-pdf": (pdf_bytes("", image_only=True), PDF),
                "over-page-limit": (pdf_bytes(*([DOCUMENT_TEXT] * 21)), PDF),
                "docx-traversal": (
                    docx_bytes("<w:p/>", extra={"../qa25-outside.txt": b"synthetic"}),
                    DOCX,
                ),
            }[case]
            accepted = await upload(client, data, media)
            keys = [row["storage_key"] for row in document_rows(engine, sid)]
            assert len(keys) == 1 and (upload_dir / keys[0]).is_file()
            assert await asyncio.wait_for(worker.run_once(), 15)
            saved = await task_result(client, accepted["task_id"], status="failed")
            assert saved["error"]["code"] == code
            assert saved["error"]["details"] == {} and saved["result"] is None
            assert PRIVATE_RESUME not in str(saved)
            assert counts(engine, sid)["profiles"] == 0
            assert counts(engine, sid)["profile_versions"] == 0
            assert not intake.parsed and gateway.calls == []
            assert intake.handles and all(handle.closed for handle in intake.handles)
            await asyncio.to_thread(app.state.platform.sweep)
            assert_cleanup_complete(engine, upload_dir, keys)
            row = document_rows(engine, sid)[0]
            assert row["status"] == "deleted" and row["storage_key"] is None

    asyncio.run(run())
    assert PRIVATE_RESUME not in caplog.text


def test_t02_parsed_document_model_failure_redacts_error_in_http_storage_and_logs(
    repo, engine, upload_dir, caplog
):
    caplog.set_level(logging.DEBUG, logger="app")

    async def run():
        app, worker, intake, gateway = assembly(
            repo, upload_dir, gateway_options={"fail_profile": True}
        )
        async with clients(app) as (client,):
            sid = (await session(client))["id"]
            accepted = await upload(client, pdf_bytes(DOCUMENT_TEXT))
            keys = [row["storage_key"] for row in document_rows(engine, sid)]
            assert await asyncio.wait_for(worker.run_once(), 15)
            assert intake.parsed[0].text == DOCUMENT_TEXT
            saved = await task_result(client, accepted["task_id"], status="failed")
            assert saved["error"]["code"] == "MODEL_OUTPUT_INVALID"
            assert saved["error"]["details"] == {} and saved["result"] is None
            assert all(handle.closed for handle in intake.handles)
            assert gateway.entered.is_set()
            with engine.connect() as connection:
                stored_error = connection.scalar(
                    text("SELECT error FROM tasks WHERE id=:id"), {"id": accepted["task_id"]}
                )
            for private in PRIVATE_FAILURE.split() + [PRIVATE_RESUME]:
                assert private not in str(saved) + str(stored_error)
            assert counts(engine, sid)["profiles"] == 0
            await asyncio.to_thread(app.state.platform.sweep)
            assert_cleanup_complete(engine, upload_dir, keys)

    asyncio.run(run())
    for private in PRIVATE_FAILURE.split() + [PRIVATE_RESUME]:
        assert private not in caplog.text


@pytest.mark.parametrize("invalidate", ["revoke", "expire"])
def test_t16_delete_or_expire_after_real_parsing_fences_late_model_and_cleans_file(
    repo, engine, upload_dir, invalidate
):
    async def run():
        app, worker, intake, gateway = assembly(repo, upload_dir, gateway_options={"pause": True})
        async with clients(app) as (client,):
            sid = (await session(client))["id"]
            token = client.cookies.get("rd_session")
            accepted = await upload(client, pdf_bytes(DOCUMENT_TEXT))
            keys = [row["storage_key"] for row in document_rows(engine, sid)]
            running = asyncio.create_task(worker.run_once())
            try:
                await asyncio.wait_for(gateway.entered.wait(), 15)
                assert intake.parsed[0].text == DOCUMENT_TEXT
                assert all(handle.closed for handle in intake.handles)
                await task_result(client, accepted["task_id"], status="running")
                if invalidate == "revoke":
                    deleted = await client.delete("/api/v1/session")
                    assert deleted.status_code == 204
                    assert "Max-Age=0" in deleted.headers["set-cookie"]
                else:
                    # Expire only the session while the task still has a valid
                    # lease/deadline: rejection must depend on session validity.
                    with engine.begin() as connection:
                        valid_task = (
                            connection.execute(
                                text("SELECT lease_until, deadline_at FROM tasks WHERE id=:id"),
                                {"id": accepted["task_id"]},
                            )
                            .mappings()
                            .one()
                        )
                        assert valid_task["lease_until"] > repo.clock()
                        assert valid_task["deadline_at"] > repo.clock()
                        connection.execute(
                            text("UPDATE sessions SET expires_at=:now WHERE id=:sid"),
                            {"now": repo.clock(), "sid": sid},
                        )
                if invalidate == "expire":
                    # Keep the expired session/task rows until the late result
                    # arrives: a missing FK alone must not satisfy this check.
                    # Do not make an HTTP request yet: its guard prunes expiry.
                    gateway.release.set()
                    await asyncio.wait_for(running, 15)
                    assert gateway.returned
                    assert counts(engine, sid)["profiles"] == 0
                    assert counts(engine, sid)["profile_versions"] == 0
                    with engine.connect() as connection:
                        saved = (
                            connection.execute(
                                text("SELECT status, result FROM tasks WHERE id=:id"),
                                {"id": accepted["task_id"]},
                            )
                            .mappings()
                            .one()
                        )
                    assert saved["status"] == "running" and saved["result"] is None
                assert (
                    await client.get(
                        f"/api/v1/tasks/{accepted['task_id']}",
                        headers={"Cookie": f"rd_session={token}"},
                    )
                ).status_code == 401
                # Revocation: clear data before the late model returns and prove
                # no resurrection. Expiry: reject while rows still exist above,
                # then prove the scheduled cleanup converges afterward.
                await asyncio.to_thread(app.state.platform.sweep)
                assert all(value == 0 for value in counts(engine, sid).values())
                assert_cleanup_complete(engine, upload_dir, keys)
            finally:
                gateway.release.set()
                await asyncio.wait_for(running, 15)
            assert gateway.returned, "The late model result must actually have been produced"
            assert all(value == 0 for value in counts(engine, sid).values())
            assert_cleanup_complete(engine, upload_dir, keys)
            assert (
                await client.get(
                    f"/api/v1/tasks/{accepted['task_id']}",
                    headers={"Cookie": f"rd_session={token}"},
                )
            ).status_code == 401

    asyncio.run(run())


def test_t15_real_document_and_diagnosis_graph_is_hidden_across_http_sessions(
    repo, engine, upload_dir
):
    async def run():
        app, worker, intake, gateway = assembly(repo, upload_dir)
        async with clients(app, 2) as (owner, outsider):
            sid = (await session(owner))["id"]
            other_sid = (await session(outsider))["id"]
            accepted = await upload(owner, pdf_bytes(DOCUMENT_TEXT))
            assert await asyncio.wait_for(worker.run_once(), 15)
            parsed = await task_result(owner, accepted["task_id"], status="succeeded")
            pid = parsed["result"]["resource_id"]
            profile = check(await owner.get(f"/api/v1/profiles/{pid}"), 200, "Profile")
            assert profile["content"]["overview"] == PRIVATE_RESUME
            assert profile["content"]["evidence"][0]["quote"] == SOURCE_QUOTE
            check(await owner.post(f"/api/v1/profiles/{pid}/confirm", json={"version": 1}), 200)
            job_accepted = check(
                await post(
                    owner,
                    "/api/v1/jobs",
                    {"raw_text": "Python", "company_context": "", "model_id": "demo-model-a"},
                ),
                202,
                "TaskAccepted",
            )
            assert await asyncio.wait_for(worker.run_once(), 15)
            parsed_job = await task_result(owner, job_accepted["task_id"], status="succeeded")
            jid = parsed_job["result"]["resource_id"]
            job = check(await owner.get(f"/api/v1/jobs/{jid}"), 200, "Job")
            check(await owner.post(f"/api/v1/jobs/{jid}/confirm", json={"version": 1}), 200)
            diagnosis_accepted = check(
                await post(
                    owner,
                    "/api/v1/diagnoses",
                    {
                        "profile": {"id": pid, "version": 1},
                        "jobs": [{"id": jid, "version": 1}],
                        "model_id": "demo-model-a",
                    },
                ),
                202,
                "DiagnosisAccepted",
            )
            assert await asyncio.wait_for(worker.run_once(), 15)
            did, tid = diagnosis_accepted["diagnosis_id"], diagnosis_accepted["task_id"]
            await task_result(owner, tid, status="succeeded")
            diagnosis = check(await owner.get(f"/api/v1/diagnoses/{did}"), 200, "Diagnosis")
            assert diagnosis["items"][0]["score_result"]["score"] == 100
            own_export = await owner.get(f"/api/v1/diagnoses/{did}/export")
            assert own_export.status_code == 200 and pid in own_export.text
            before = counts(engine, sid)
            requests = [
                ("GET", f"/api/v1/profiles/{pid}", None),
                ("GET", f"/api/v1/profiles/{pid}?version=1", None),
                ("GET", f"/api/v1/profiles/{pid}/messages", None),
                (
                    "PUT",
                    f"/api/v1/profiles/{pid}",
                    {"base_version": 1, "content": deepcopy(profile["content"])},
                ),
                ("POST", f"/api/v1/profiles/{pid}/confirm", {"version": 1}),
                ("GET", f"/api/v1/jobs/{jid}", None),
                (
                    "PUT",
                    f"/api/v1/jobs/{jid}",
                    {"base_version": 1, "raw_text": "Python", "content": job["content"]},
                ),
                ("POST", f"/api/v1/jobs/{jid}/confirm", {"version": 1}),
                ("GET", f"/api/v1/tasks/{accepted['task_id']}", None),
                ("GET", f"/api/v1/tasks/{tid}", None),
                ("GET", f"/api/v1/diagnoses/{did}", None),
                ("GET", f"/api/v1/diagnoses/{did}/export", None),
            ]
            for method, path, body in requests:
                kwargs = {"json": body} if body is not None else {}
                response = await outsider.request(method, path, **kwargs)
                check(response, 404, code="RESOURCE_NOT_FOUND")
                assert PRIVATE_RESUME not in response.text and SOURCE_QUOTE not in response.text
                assert "score_result" not in response.text
            assert counts(engine, sid) == before
            assert all(value == 0 for value in counts(engine, other_sid).values())
            unchanged = check(await owner.get(f"/api/v1/profiles/{pid}"), 200, "Profile")
            assert unchanged["version"] == 1 and unchanged["confirmed"] is True
            assert unchanged["content"] == profile["content"]
            assert (await owner.get(f"/api/v1/diagnoses/{did}/export")).text == own_export.text
            assert intake.parsed and [call.task_name for call in gateway.calls] == [
                "profile_extract",
                "job_extract",
                "diagnosis_report",
            ]
            await asyncio.to_thread(app.state.platform.sweep)

    asyncio.run(run())
