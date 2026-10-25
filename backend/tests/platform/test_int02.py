"""INT-02 HTTP + PostgreSQL + delivered business modules, with fake models only.

HTTP is exercised through ASGI, and a durable worker is advanced explicitly in
this process. These tests do not claim independent-process or browser coverage.
Only test-owned sessions/IDs and registered synthetic source texts are used.
"""

# ruff: noqa: F811 -- PostgreSQL fixtures are imported for pytest injection.

import asyncio
import copy
import io
import zipfile
from contextlib import asynccontextmanager
from uuid import uuid4
from xml.sax.saxutils import escape

import httpx
import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import text  # noqa: E402

from app.database import create_app  # noqa: E402
from app.llm import FakeModelDirectory, GatewayError  # noqa: E402
from app.platform.demo_gateway import JOB_TEXTS, PROFILE_TEXT, IntegrationFakeGateway  # noqa: E402
from app.platform.jobs.worker import create_worker  # noqa: E402
from app.platform.repositories import PostgreSQLRepository  # noqa: E402
from app.settings import Settings  # noqa: E402

from .test_api import ORIGIN, check, post, session  # noqa: E402
from .test_postgres import (  # noqa: E402
    counts,
    engine,  # noqa: F401
    repo,  # noqa: F401
    upload_dir,  # noqa: F401
)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MODEL = "demo-model-a"
EMPTY_PROFILE = {"content": {"overview": "", "as_of_month": "2026-09", "facts": [], "evidence": []}}


def docx_bytes():
    """A real Word XML ZIP; every paragraph contains registered source text."""
    buffer = io.BytesIO()
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>"
        for line in PROFILE_TEXT.strip().splitlines()
    )
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="word/document.xml" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{paragraphs}</w:body></w:document>",
        )
    return buffer.getvalue()


@asynccontextmanager
async def client_for(app, *, cookies=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": ORIGIN},
        cookies=cookies,
    ) as client:
        yield client


@pytest.fixture
def stack(repo, engine, upload_dir):
    settings = Settings(
        _env_file=None,
        database_url=engine.url.render_as_string(hide_password=False),
        upload_dir=upload_dir,
    )
    gateway = IntegrationFakeGateway(FakeModelDirectory())
    app = create_app(settings, repository=repo, gateway=gateway)
    worker = create_worker(settings, repository=repo, gateway=gateway)
    return app, worker, settings, gateway


async def finish(client, worker, accepted, *, status="succeeded"):
    task_id = accepted["task_id"]
    before = check(await client.get(f"/api/v1/tasks/{task_id}"), 200, "Task")
    assert before["status"] == "queued", "API must persist work without executing it"
    assert await worker.run_once(), "The database queue must contain the accepted task"
    task = check(await client.get(f"/api/v1/tasks/{task_id}"), 200, "Task")
    assert task["status"] == status, task
    return task


async def upload(client, data=None, *, name="synthetic.docx", media=DOCX):
    return await client.post(
        "/api/v1/documents",
        files={"file": (name, docx_bytes() if data is None else data, media)},
        data={"model_id": MODEL},
        headers={"Idempotency-Key": str(uuid4())},
    )


async def prepared_profile(client, worker, route="upload"):
    if route == "upload":
        accepted = check(await upload(client), 202, "TaskAccepted")
        task = await finish(client, worker, accepted)
        assert any(w.startswith("DOCX_PAGINATION_UNVERIFIED:") for w in task["result"]["warnings"])
        profile = check(
            await client.get(f"/api/v1/profiles/{task['result']['resource_id']}"), 200, "Profile"
        )
        assert len(profile["content"]["facts"]) == 3
        assert all(e["locator"] for e in profile["content"]["evidence"])
        assert all(e["source_type"] == "document" for e in profile["content"]["evidence"])
    else:
        profile = check(await post(client, "/api/v1/profiles", EMPTY_PROFILE), 201, "Profile")
        # The second turn must retain the first turn's verified fact/source.
        lines = PROFILE_TEXT.strip().splitlines()
        for content in (lines[0], PROFILE_TEXT):
            accepted = check(
                await post(
                    client,
                    f"/api/v1/profiles/{profile['id']}/messages",
                    {"base_version": profile["version"], "content": content, "model_id": MODEL},
                ),
                202,
                "TaskAccepted",
            )
            task = await finish(client, worker, accepted)
            profile = check(await client.get(f"/api/v1/profiles/{profile['id']}"), 200, "Profile")
            assert profile["version"] == task["result"]["version"]
        assert profile["version"] == 3 and len(profile["content"]["facts"]) == 3
        messages = check(
            await client.get(f"/api/v1/profiles/{profile['id']}/messages"), 200, "MessageList"
        )["items"]
        users = {m["id"]: m["content"] for m in messages if m["role"] == "user"}
        assert len(users) == 2 and len(messages) == 4
        assert len({e["source_id"] for e in profile["content"]["evidence"]}) == 2
        for evidence in profile["content"]["evidence"]:
            assert evidence["source_type"] == "message"
            assert evidence["quote"] in users[evidence["source_id"]]
    return check(
        await client.post(
            f"/api/v1/profiles/{profile['id']}/confirm", json={"version": profile["version"]}
        ),
        200,
        "Profile",
    )


async def prepared_job(client, worker, raw_text=JOB_TEXTS[0]):
    accepted = check(
        await post(
            client,
            "/api/v1/jobs",
            {"raw_text": raw_text, "company_context": "", "model_id": MODEL},
        ),
        202,
        "TaskAccepted",
    )
    task = await finish(client, worker, accepted)
    job = check(await client.get(f"/api/v1/jobs/{task['result']['resource_id']}"), 200, "Job")
    return check(
        await client.post(f"/api/v1/jobs/{job['id']}/confirm", json={"version": job["version"]}),
        200,
        "Job",
    )


def diagnosis_body(profile, jobs):
    return {
        "profile": {"id": profile["id"], "version": profile["version"]},
        "jobs": [{"id": job["id"], "version": job["version"]} for job in jobs],
        "model_id": MODEL,
    }


async def diagnose(client, worker, profile, jobs, *, status="succeeded"):
    accepted = check(
        await post(client, "/api/v1/diagnoses", diagnosis_body(profile, jobs)),
        202,
        "DiagnosisAccepted",
    )
    check(
        await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}/export"),
        409,
        code="NOT_READY",
    )
    task = await finish(client, worker, accepted, status=status)
    diagnosis = check(
        await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}"), 200, "Diagnosis"
    )
    assert task["result"]["resource_id"] == diagnosis["id"]
    return diagnosis


@pytest.mark.parametrize("route", ["upload", "chat"])
@pytest.mark.parametrize("number", [1, 5])
def test_t01_t03_t05_t23_business_routes_and_recreated_api(stack, repo, engine, route, number):
    async def run():
        app, worker, settings, gateway = stack
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            check(await client.get("/api/v1/models"), 200, "ModelList")
            profile = await prepared_profile(client, worker, route)
            jobs = [await prepared_job(client, worker, raw) for raw in JOB_TEXTS[:number]]
            diagnosis = await diagnose(client, worker, profile, jobs)
            assert diagnosis["profile"] == diagnosis_body(profile, jobs)["profile"]
            evidence = {e["id"] for e in profile["content"]["evidence"]}
            for item, job in zip(diagnosis["items"], jobs, strict=True):
                assert item["job"] == {"id": job["id"], "version": job["version"]}
                assert item["status"] == "succeeded" and item["error"] is None
                assert item["model_metadata"]["provider"] == "fake"
                assert "演示数据" in item["report"]["summary"]
                assessments = item["score_result"]["assessments"]
                assert {a["requirement_id"] for a in assessments} == {
                    r["id"] for r in job["content"]["requirements"] if not r["ignored"]
                }
                assert all(set(a["evidence_ids"]) <= evidence for a in assessments)
                if route == "upload":
                    assert all(
                        e["source_id"] != "manual-revision-1"
                        for e in profile["content"]["evidence"]
                    )
            if number == 5:
                assert len({item["score_result"]["score"] for item in diagnosis["items"]}) > 1
                assert len({job["content"]["title"] for job in jobs}) == 5
            exported = check(await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export"), 200)
            assert exported.headers["content-type"].startswith("text/markdown")
            assert "attachment" in exported.headers["content-disposition"]
            assert profile["id"] in exported.text
            for item in diagnosis["items"]:
                assert item["job"]["id"] in exported.text
                assert str(item["score_result"]["score"]) in exported.text
            cookies = httpx.Cookies(client.cookies)
            calls = len(gateway.calls)
            # A new engine/repository/API has no access to the previous Python objects.
            restarted_repo = PostgreSQLRepository(engine.url.render_as_string(hide_password=False))
            try:
                restarted = create_app(settings, repository=restarted_repo)
                async with client_for(restarted, cookies=cookies) as refreshed:
                    assert (
                        check(
                            await refreshed.get(f"/api/v1/diagnoses/{diagnosis['id']}"),
                            200,
                            "Diagnosis",
                        )
                        == diagnosis
                    )
                    assert (
                        check(
                            await refreshed.get(f"/api/v1/profiles/{profile['id']}"), 200, "Profile"
                        )
                        == profile
                    )
                    assert (
                        await refreshed.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
                    ).text == exported.text
                    assert len(gateway.calls) == calls, "Reading/export must not invoke the model"
            finally:
                restarted_repo.close()
            if route == "upload":
                with engine.connect() as connection:
                    document_ids = set(
                        connection.scalars(
                            text("SELECT id::text FROM documents WHERE session_id=:sid"),
                            {"sid": sid},
                        )
                    )
                assert {e["source_id"] for e in profile["content"]["evidence"]} == document_ids

    asyncio.run(run())


def test_t04_edit_confirm_rediagnose_freezes_old_versions(stack):
    async def run():
        app, worker, _, _ = stack
        async with client_for(app) as client:
            await session(client)
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker)
            old = await diagnose(client, worker, profile, [job])
            old_export = (await client.get(f"/api/v1/diagnoses/{old['id']}/export")).text
            content = copy.deepcopy(profile["content"])
            content["facts"][0]["polarity"] = "negative"
            profile_update = {"base_version": profile["version"], "content": content}
            updated = check(
                await client.put(f"/api/v1/profiles/{profile['id']}", json=profile_update),
                200,
                "Profile",
            )
            check(
                await client.put(f"/api/v1/profiles/{profile['id']}", json=profile_update),
                409,
                code="VERSION_CONFLICT",
            )
            await client.post(
                f"/api/v1/profiles/{profile['id']}/confirm", json={"version": updated["version"]}
            )
            changed = copy.deepcopy(job["content"])
            changed["requirements"][0]["target"] = "Kubernetes"
            changed["requirements"][0]["quote"] = "必须具备 Kubernetes 应用能力。"
            edited_job = check(
                await client.put(
                    f"/api/v1/jobs/{job['id']}",
                    json={
                        "base_version": job["version"],
                        "raw_text": "\n".join(r["quote"] for r in changed["requirements"]),
                        "content": changed,
                    },
                ),
                200,
                "Job",
            )
            check(
                await post(client, "/api/v1/diagnoses", diagnosis_body(updated, [edited_job])),
                422,
                code="UNCONFIRMED_VERSION",
            )
            edited_job = check(
                await client.post(
                    f"/api/v1/jobs/{job['id']}/confirm", json={"version": edited_job["version"]}
                ),
                200,
                "Job",
            )
            newer = await diagnose(client, worker, updated, [edited_job])
            assert newer["profile"]["version"] == profile["version"] + 1
            assert newer["items"][0]["job"]["version"] == job["version"] + 1
            assert newer["items"][0]["score_result"] != old["items"][0]["score_result"]
            assert (
                check(await client.get(f"/api/v1/diagnoses/{old['id']}"), 200, "Diagnosis") == old
            )
            assert (await client.get(f"/api/v1/diagnoses/{old['id']}/export")).text == old_export
            assert (
                check(
                    await client.get(
                        f"/api/v1/profiles/{profile['id']}?version={profile['version']}"
                    ),
                    200,
                    "Profile",
                )["content"]
                == profile["content"]
            )
            assert (
                check(
                    await client.get(f"/api/v1/jobs/{job['id']}?version={job['version']}"),
                    200,
                    "Job",
                )["content"]
                == job["content"]
            )

    asyncio.run(run())


def test_t02_scan_and_disguised_file_never_create_profile(stack, repo, engine):
    from pypdf import PdfWriter

    async def run():
        app, worker, _, _ = stack
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            check(
                await upload(client, b"not a PDF", name="fake.pdf", media="application/pdf"),
                415,
                code="UNSUPPORTED_FILE_TYPE",
            )
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            buffer = io.BytesIO()
            writer.write(buffer)
            accepted = check(
                await upload(
                    client, buffer.getvalue(), name="no-text.pdf", media="application/pdf"
                ),
                202,
                "TaskAccepted",
            )
            task = await finish(client, worker, accepted, status="failed")
            assert task["error"]["code"] == "NO_TEXT_LAYER" and task["result"] is None
            assert counts(engine, sid)["profiles"] == 0
            assert counts(engine, sid)["profile_versions"] == 0
            # The multipart signature check accepts this ZIP; M3 rejects its invalid Word package.
            invalid_word = io.BytesIO()
            with zipfile.ZipFile(invalid_word, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
            accepted = check(await upload(client, invalid_word.getvalue()), 202, "TaskAccepted")
            task = await finish(client, worker, accepted, status="failed")
            assert task["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
            assert counts(engine, sid)["profiles"] == 0
            # A file with PDF signature but invalid body must not produce a draft either.
            accepted = check(
                await upload(
                    client, b"%PDF-1.7\ninvalid", name="broken.pdf", media="application/pdf"
                ),
                202,
                "TaskAccepted",
            )
            task = await finish(client, worker, accepted, status="failed")
            assert task["error"]["code"] == "DOCUMENT_PARSE_FAILED"
            assert counts(engine, sid)["profiles"] == 0

    asyncio.run(run())


def test_t06_t15_invalid_inputs_and_foreign_resources_are_rejected_atomically(stack, engine):
    async def run():
        app, worker, _, _ = stack
        async with client_for(app) as client, client_for(app) as foreign:
            sid = (await session(client))["id"]
            await session(foreign)
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker)
            body = diagnosis_body(profile, [job])
            before = counts(engine, sid)
            check(
                await post(
                    client,
                    "/api/v1/jobs",
                    {"raw_text": "", "company_context": "", "model_id": MODEL},
                ),
                422,
                code="VALIDATION_ERROR",
            )
            check(
                await post(client, "/api/v1/diagnoses", {**body, "jobs": body["jobs"] * 6}),
                422,
                code="VALIDATION_ERROR",
            )
            check(
                await post(
                    client,
                    "/api/v1/diagnoses",
                    {**body, "jobs": [{"id": str(uuid4()), "version": 1}]},
                ),
                404,
                code="RESOURCE_NOT_FOUND",
            )
            check(
                await post(
                    client,
                    "/api/v1/diagnoses",
                    {**body, "profile": {"id": profile["id"], "version": 999}},
                ),
                404,
                code="RESOURCE_NOT_FOUND",
            )
            check(
                await foreign.get(f"/api/v1/profiles/{profile['id']}"),
                404,
                code="RESOURCE_NOT_FOUND",
            )
            check(await foreign.get(f"/api/v1/jobs/{job['id']}"), 404, code="RESOURCE_NOT_FOUND")
            check(
                await foreign.put(
                    f"/api/v1/jobs/{job['id']}",
                    json={
                        "base_version": 1,
                        "raw_text": job["raw_text"],
                        "content": job["content"],
                    },
                ),
                404,
                code="RESOURCE_NOT_FOUND",
            )
            invalid_profile = copy.deepcopy(profile["content"])
            invalid_profile["facts"][0]["evidence_ids"] = ["not-in-this-profile"]
            check(
                await client.put(
                    f"/api/v1/profiles/{profile['id']}",
                    json={"base_version": profile["version"], "content": invalid_profile},
                ),
                422,
                code="VALIDATION_ERROR",
            )
            check(await post(foreign, "/api/v1/diagnoses", body), 404, code="RESOURCE_NOT_FOUND")
            assert counts(engine, sid) == before
            ignored = copy.deepcopy(job["content"])
            for requirement in ignored["requirements"]:
                requirement.update(ignored=True, ignore_reason="合成验收忽略")
            edited = check(
                await client.put(
                    f"/api/v1/jobs/{job['id']}",
                    json={"base_version": 1, "raw_text": job["raw_text"], "content": ignored},
                ),
                200,
                "Job",
            )
            check(
                await client.post(
                    f"/api/v1/jobs/{job['id']}/confirm", json={"version": edited["version"]}
                ),
                200,
                "Job",
            )
            before = counts(engine, sid)
            check(
                await post(client, "/api/v1/diagnoses", diagnosis_body(profile, [edited])),
                422,
                code="NO_SCORABLE_REQUIREMENTS",
            )
            assert counts(engine, sid) == before

    asyncio.run(run())


class SelectiveReportFailure(IntegrationFakeGateway):
    failing_job_id = None
    failure_code = "MODEL_TIMEOUT"

    async def _produce(self, task_name, prompt_context, behavior):
        if (
            task_name == "diagnosis_report"
            and prompt_context["job_snapshot"]["id"] == self.failing_job_id
        ):
            if self.failure_code == "MODEL_TIMEOUT":
                raise GatewayError("MODEL_TIMEOUT", "Synthetic selective model failure")
            behavior = {
                "MODEL_OUTPUT_INVALID": "invalid_json",
                "PROVIDER_UNAVAILABLE": "provider_unavailable",
            }[self.failure_code]
        return await super()._produce(task_name, prompt_context, behavior)


@pytest.mark.parametrize(
    "failure_code", ["MODEL_TIMEOUT", "MODEL_OUTPUT_INVALID", "PROVIDER_UNAVAILABLE"]
)
def test_t11_t12_partial_keeps_stored_score_and_foreign_export_hidden(stack, repo, failure_code):
    async def run():
        app, _, settings, _ = stack
        gateway = SelectiveReportFailure(FakeModelDirectory())
        gateway.failure_code = failure_code
        worker = create_worker(settings, repository=repo, gateway=gateway)
        async with client_for(app) as client, client_for(app) as foreign:
            await session(client)
            await session(foreign)
            profile = await prepared_profile(client, worker)
            jobs = [await prepared_job(client, worker, raw) for raw in JOB_TEXTS[:2]]
            gateway.failing_job_id = jobs[1]["id"]
            diagnosis = await diagnose(client, worker, profile, jobs, status="partial")
            assert [item["status"] for item in diagnosis["items"]] == ["succeeded", "score_only"]
            failed = diagnosis["items"][1]
            assert failed["report"] is None and failed["score_result"] is not None
            assert failed["error"]["code"] == failure_code
            if failure_code != "MODEL_TIMEOUT":
                attempts = [call for call in gateway.calls if call.outcome == failure_code]
                assert len(attempts) == 1 and attempts[0].attempts == 2
            exported = check(
                await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export"), 200
            ).text
            assert failure_code in exported
            assert str(failed["score_result"]["score"]) in exported
            assert jobs[0]["id"] in exported and jobs[1]["id"] in exported
            for path in (
                f"/api/v1/diagnoses/{diagnosis['id']}",
                f"/api/v1/diagnoses/{diagnosis['id']}/export",
                f"/api/v1/tasks/{diagnosis['task_id']}",
            ):
                check(await foreign.get(path), 404, code="RESOURCE_NOT_FOUND")

    asyncio.run(run())


class BlockedReport(IntegrationFakeGateway):
    def __init__(self, directory):
        super().__init__(directory)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def _produce(self, task_name, prompt_context, behavior):
        if task_name == "diagnosis_report":
            self.started.set()
            await self.release.wait()
        return await super()._produce(task_name, prompt_context, behavior)


def test_t16_revoke_during_real_report_call_prevents_writeback(stack, repo, engine):
    async def run():
        app, _, settings, _ = stack
        gateway = BlockedReport(FakeModelDirectory())
        worker = create_worker(settings, repository=repo, gateway=gateway)
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker)
            accepted = check(
                await post(client, "/api/v1/diagnoses", diagnosis_body(profile, [job])),
                202,
                "DiagnosisAccepted",
            )
            work = asyncio.create_task(worker.run_once())
            try:
                await asyncio.wait_for(gateway.started.wait(), timeout=5)
                check(await client.delete("/api/v1/session"), 204)
                assert counts(engine, sid)["diagnoses"] == 0
                gateway.release.set()
                assert await asyncio.wait_for(work, timeout=5)
                assert all(value == 0 for value in counts(engine, sid).values())
                check(await client.get(f"/api/v1/tasks/{accepted['task_id']}"), 401)
            finally:
                gateway.release.set()
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)

    asyncio.run(run())


def test_no_score_failure_is_readable_but_cannot_export(stack, monkeypatch):
    async def run():
        app, worker, _, _ = stack
        async with client_for(app) as client:
            await session(client)
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker)

            # Controlled failure at the scoring call boundary; no alternative scoring implementation.
            def fail_scoring(*args, **kwargs):
                raise RuntimeError("Synthetic scoring fault")

            monkeypatch.setattr(worker.scoring, "assess_requirements", fail_scoring)
            diagnosis = await diagnose(client, worker, profile, [job], status="failed")
            item = diagnosis["items"][0]
            assert item["status"] == "failed"
            assert item["score_result"] is None and item["report"] is None
            check(
                await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export"),
                409,
                code="NOT_READY",
            )

    asyncio.run(run())


def test_t06_six_distinct_confirmed_jobs_rejected_without_partial_writes(stack, engine):
    async def run():
        app, worker, _, gateway = stack
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            profile = await prepared_profile(client, worker)
            # Reusing source text creates a sixth resource, not a duplicate reference.
            jobs = [
                await prepared_job(client, worker, raw_text)
                for raw_text in (*JOB_TEXTS, JOB_TEXTS[0])
            ]
            assert len(jobs) == len({job["id"] for job in jobs}) == 6
            assert all(job["confirmed"] for job in jobs)
            before = counts(engine, sid)
            assert before["diagnoses"] == before["diagnosis_items"] == 0
            calls = len(gateway.calls)
            check(
                await post(client, "/api/v1/diagnoses", diagnosis_body(profile, jobs)),
                422,
                code="VALIDATION_ERROR",
            )
            assert counts(engine, sid) == before
            assert len(gateway.calls) == calls

    asyncio.run(run())
