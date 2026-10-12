"""API-01 acceptance through ASGI HTTP and separate httpx cookie jars, no paid keys."""

import asyncio
import copy
import io
import zipfile
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.contracts import Model, ModelList
from app.main import create_app
from app.platform.catalog import FakeModelCatalog
from app.platform.fakes import FakeIntake, FakeTaskExecutor
from app.platform.repositories import InMemoryRepository
from app.settings import Settings
from app.tools.check_contracts import compare_routes, example_validator, load_design

ORIGIN = "http://localhost:5173"
PROFILE = {
    "content": {
        "overview": "synthetic-private-marker",
        "as_of_month": "2026-09",
        "facts": [],
        "evidence": [],
    }
}
JOB = {"raw_text": "合成 JD：需要 Python。", "company_context": "", "model_id": "demo-model-a"}
DESIGN = load_design()


def check(response, status, schema=None, code=None):
    assert response.status_code == status, response.text
    if status >= 400:
        schema = "Error"
    if schema:
        example_validator(DESIGN, schema).validate(response.json())
    if code:
        assert response.json()["error"]["code"] == code
    return response.json() if schema else response


async def post(client, path, body, *, key=None):
    return await client.post(path, json=body, headers={"Idempotency-Key": key or str(uuid4())})


async def session(client):
    return check(
        await client.post("/api/v1/session", json={"consent_version": "v1"}), 200, "Session"
    )


async def poll(client, task_id):
    states = []
    for _ in range(200):
        task = check(await client.get(f"/api/v1/tasks/{task_id}"), 200, "Task")
        states.append(task["status"])
        if task["status"] in {"succeeded", "partial", "failed"}:
            return task, states
        await asyncio.sleep(0.005)
    pytest.fail("task did not reach a terminal state")


@asynccontextmanager
async def clients(app, count=1):
    async with AsyncExitStack() as stack:
        values = [
            await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://test",
                    headers={"Origin": ORIGIN},
                )
            )
            for _ in range(count)
        ]
        try:
            yield values
        finally:
            await app.state.platform.close()


def app_for(**kwargs):
    return create_app(Settings(_env_file=None), **kwargs)


async def graph(client, *, chat=False):
    profile = check(await post(client, "/api/v1/profiles", PROFILE), 201, "Profile")
    pid = profile["id"]
    if chat:
        accepted = check(
            await post(
                client,
                f"/api/v1/profiles/{pid}/messages",
                {
                    "base_version": 1,
                    "content": "合成用户经历。",
                    "model_id": "demo-model-a",
                },
            ),
            202,
            "TaskAccepted",
        )
        task, _ = await poll(client, accepted["task_id"])
        assert task["status"] == "succeeded"
        profile = check(
            await client.get(f"/api/v1/profiles/{pid}?version={task['result']['version']}"),
            200,
            "Profile",
        )
        messages = check(await client.get(f"/api/v1/profiles/{pid}/messages"), 200, "MessageList")
        assert [m["role"] for m in messages["items"]] == ["user", "assistant"]
    profile = check(
        await client.post(f"/api/v1/profiles/{pid}/confirm", json={"version": profile["version"]}),
        200,
        "Profile",
    )
    accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
    job_task, _ = await poll(client, accepted["task_id"])
    assert job_task["status"] == "succeeded"
    jid = job_task["result"]["resource_id"]
    job = check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job")
    job = check(await client.post(f"/api/v1/jobs/{jid}/confirm", json={"version": 1}), 200, "Job")
    body = {
        "profile": {"id": pid, "version": profile["version"]},
        "jobs": [{"id": jid, "version": 1}],
        "model_id": "demo-model-a",
    }
    accepted = check(await post(client, "/api/v1/diagnoses", body), 202, "DiagnosisAccepted")
    task, states = await poll(client, accepted["task_id"])
    assert task["status"] == "succeeded"
    diagnosis = check(
        await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}"), 200, "Diagnosis"
    )
    return {
        "profile": profile,
        "job": job,
        "diagnosis": diagnosis,
        "task": task,
        "body": body,
        "states": states,
    }


def test_successful_http_chain_and_export():
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            models = check(await client.get("/api/v1/models"), 200, "ModelList")
            assert models["default_model_id"] in {m["id"] for m in models["items"]}
            assert all(
                m["provider"] == "fake" and "演示" in m["display_name"] for m in models["items"]
            )
            assert "api_key" not in str(models) and "base_url" not in str(models)
            result = await graph(client, chat=True)
            task, diagnosis = result["task"], result["diagnosis"]
            assert {"running", "succeeded"} <= set(result["states"])
            assert task["result"]["resource_id"] == diagnosis["id"]
            item = diagnosis["items"][0]
            assert item["status"] == "succeeded" and item["error"] is None
            assert item["model_metadata"]["provider"] == "fake"
            assert item["score_result"]["unknown_weight_ratio"] == 1
            exported = check(await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export"), 200)
            assert exported.headers["content-type"].startswith("text/markdown")
            assert exported.headers["content-disposition"] == 'attachment; filename="diagnosis.md"'
            assert "演示数据" in exported.text and result["profile"]["id"] in exported.text

    asyncio.run(run())


@pytest.mark.parametrize(
    "route",
    [
        "profile_get",
        "profile_history",
        "profile_put",
        "profile_confirm",
        "messages_get",
        "messages_post",
        "job_get",
        "job_history",
        "job_put",
        "job_confirm",
        "task_get",
        "diagnosis_get",
        "export",
        "diagnosis_post",
    ],
)
def test_t15_every_owned_route_404_and_no_cookie_401(route):
    async def run():
        app = app_for()
        async with clients(app, 3) as (owner, foreign, anonymous):
            assert (await session(owner))["id"] != (await session(foreign))["id"]
            result = await graph(owner)
            profile, job, diagnosis, task = (
                result[k] for k in ("profile", "job", "diagnosis", "task")
            )
            pid, jid, did, tid = profile["id"], job["id"], diagnosis["id"], task["id"]
            routes = {
                "profile_get": ("GET", f"/profiles/{pid}", None),
                "profile_history": ("GET", f"/profiles/{pid}?version=1", None),
                "profile_put": (
                    "PUT",
                    f"/profiles/{pid}",
                    {"base_version": 1, "content": profile["content"]},
                ),
                "profile_confirm": ("POST", f"/profiles/{pid}/confirm", {"version": 1}),
                "messages_get": ("GET", f"/profiles/{pid}/messages", None),
                "messages_post": (
                    "POST",
                    f"/profiles/{pid}/messages",
                    {"base_version": 1, "content": "合成消息", "model_id": "demo-model-a"},
                ),
                "job_get": ("GET", f"/jobs/{jid}", None),
                "job_history": ("GET", f"/jobs/{jid}?version=1", None),
                "job_put": (
                    "PUT",
                    f"/jobs/{jid}",
                    {"base_version": 1, "raw_text": job["raw_text"], "content": job["content"]},
                ),
                "job_confirm": ("POST", f"/jobs/{jid}/confirm", {"version": 1}),
                "task_get": ("GET", f"/tasks/{tid}", None),
                "diagnosis_get": ("GET", f"/diagnoses/{did}", None),
                "export": ("GET", f"/diagnoses/{did}/export", None),
                "diagnosis_post": ("POST", "/diagnoses", result["body"]),
            }
            method, path, body = routes[route]
            for client, status, code in (
                (foreign, 404, "RESOURCE_NOT_FOUND"),
                (anonymous, 401, "SESSION_EXPIRED"),
            ):
                response = await client.request(
                    method, "/api/v1" + path, json=body, headers={"Idempotency-Key": str(uuid4())}
                )
                check(response, status, code=code)
                for secret in (pid, jid, did, "synthetic-private-marker", job["raw_text"]):
                    assert secret not in response.text
            missing = check(
                await foreign.get(f"/api/v1/profiles/{uuid4()}"), 404, code="RESOURCE_NOT_FOUND"
            )
            # A real other-owner resource and a nonexistent one share the same error.
            if route == "profile_get":
                actual = (await foreign.get("/api/v1" + path)).json()
                assert actual["error"] == missing["error"]

    asyncio.run(run())


def test_cookie_reuse_expiry_secure_origin_and_revocation():
    async def run():
        current = [datetime(2026, 10, 12, tzinfo=UTC)]
        repository = InMemoryRepository(clock=lambda: current[0])
        app = create_app(
            Settings(_env_file=None, session_cookie_secure=True), repository=repository
        )
        # HTTPS is necessary for the real cookie jar to send a Secure cookie.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://test",
            headers={"Origin": ORIGIN},
        ) as client:
            response = await client.post("/api/v1/session", json={"consent_version": "v1"})
            first = check(response, 200, "Session")
            assert (
                "HttpOnly" in response.headers["set-cookie"]
                and "Secure" in response.headers["set-cookie"]
            )
            assert "SameSite=lax" in response.headers["set-cookie"]
            token = client.cookies.get("rd_session")
            assert token not in repr(repository.sessions)
            current[0] += timedelta(days=1)
            assert await session(client) == first
            check(
                await client.post(
                    "/api/v1/session",
                    json={"consent_version": "v1"},
                    headers={"Origin": "https://untrusted.test"},
                ),
                403,
                code="ORIGIN_FORBIDDEN",
            )
            check(await client.delete("/api/v1/session"), 204)
            assert client.cookies.get("rd_session") is None
            check(
                await client.get("/api/v1/models", headers={"Cookie": f"rd_session={token}"}),
                401,
                code="SESSION_EXPIRED",
            )
            await session(client)
            current[0] += timedelta(days=7)
            check(await client.get("/api/v1/models"), 401, code="SESSION_EXPIRED")
            assert not repository.sessions
        await app.state.platform.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "body,headers",
    [
        ({"content": {"overview": "synthetic-sensitive-value"}}, {}),
        (PROFILE, {"Idempotency-Key": "short"}),
        ({**PROFILE, "synthetic-sensitive-value": "do-not-echo"}, {}),
    ],
)
def test_fastapi_validation_has_error_schema_without_input(body, headers):
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            response = await client.post(
                "/api/v1/profiles", json=body, headers={"Idempotency-Key": str(uuid4()), **headers}
            )
            check(response, 422, code="VALIDATION_ERROR")
            assert (
                "synthetic-sensitive-value" not in response.text
                and "do-not-echo" not in response.text
            )
            check(await client.get("/api/v1/profiles/not-a-uuid"), 422, code="VALIDATION_ERROR")
            check(
                await client.post(
                    "/api/v1/jobs",
                    content=b'{"raw_text":',
                    headers={"Content-Type": "application/json"},
                ),
                422,
                code="VALIDATION_ERROR",
            )

    asyncio.run(run())


def test_failures_are_terminal_and_sanitized(caplog):
    class BrokenIntake(FakeIntake):
        async def extract_job(self, *args, **kwargs):
            raise RuntimeError("synthetic-token /private/sensitive/path raw-resume-marker")

    async def run():
        executor = FakeTaskExecutor(failures={"job_parse": "MODEL_TIMEOUT"})
        app = app_for(executor=executor)
        async with clients(app) as (client,):
            await session(client)
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            assert (
                task["status"] == "failed"
                and task["result"] is None
                and task["error"]["code"] == "MODEL_TIMEOUT"
            )
            executor.failures.clear()
            app.state.platform.intake = BrokenIntake()
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            assert task["error"]["code"] == "INTERNAL_ERROR"
            assert "sensitive" not in str(task) and "raw-resume-marker" not in str(task)
            assert not app.state.platform.repo.jobs

    asyncio.run(run())
    assert "synthetic-token" not in caplog.text and "raw-resume-marker" not in caplog.text


def test_running_revoke_prevents_late_writes():
    async def run():
        gate = asyncio.Event()
        executor = FakeTaskExecutor(gate=gate)
        app = app_for(executor=executor)
        async with clients(app) as (client,):
            await session(client)
            token = client.cookies.get("rd_session")
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            await asyncio.wait_for(executor.started.wait(), timeout=1)
            task = check(await client.get(f"/api/v1/tasks/{accepted['task_id']}"), 200, "Task")
            assert task["status"] == "running"
            check(await client.delete("/api/v1/session"), 204)
            gate.set()
            await app.state.platform.drain()
            check(
                await client.get(
                    f"/api/v1/tasks/{accepted['task_id']}",
                    headers={"Cookie": f"rd_session={token}"},
                ),
                401,
                code="SESSION_EXPIRED",
            )
            repository = app.state.platform.repo
            assert not repository.tasks and not repository.jobs and not repository.sessions

    asyncio.run(run())


def test_idempotency_busy_limit_and_version_conflict():
    async def run():
        executor = FakeTaskExecutor(gate=asyncio.Event())
        app = app_for(executor=executor)
        async with clients(app) as (client,):
            await session(client)
            key = str(uuid4())
            profile = check(
                await post(client, "/api/v1/profiles", PROFILE, key=key), 201, "Profile"
            )
            assert (
                check(await post(client, "/api/v1/profiles", PROFILE, key=key), 201, "Profile")
                == profile
            )
            changed = copy.deepcopy(PROFILE)
            changed["content"]["overview"] = "changed"
            check(
                await post(client, "/api/v1/profiles", changed, key=key),
                409,
                code="IDEMPOTENCY_CONFLICT",
            )
            pid = profile["id"]
            body = {"base_version": 1, "content": "合成消息", "model_id": "demo-model-a"}
            chat_key = str(uuid4())
            accepted = check(
                await post(client, f"/api/v1/profiles/{pid}/messages", body, key=chat_key),
                202,
                "TaskAccepted",
            )
            assert (
                check(
                    await post(client, f"/api/v1/profiles/{pid}/messages", body, key=chat_key),
                    202,
                    "TaskAccepted",
                )
                == accepted
            )
            check(
                await post(client, f"/api/v1/profiles/{pid}/messages", body),
                409,
                code="PROFILE_BUSY",
            )
            check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            response = await post(client, "/api/v1/jobs", JOB)
            check(response, 429, code="RATE_LIMITED")
            assert response.headers["Retry-After"] == "2"
            update = {"base_version": 1, "content": profile["content"]}
            check(await client.put(f"/api/v1/profiles/{pid}", json=update), 200, "Profile")
            check(
                await client.put(f"/api/v1/profiles/{pid}", json=update),
                409,
                code="VERSION_CONFLICT",
            )
            executor.gate.set()
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["error"]["code"] == "VERSION_CONFLICT"
            messages = check(
                await client.get(f"/api/v1/profiles/{pid}/messages"), 200, "MessageList"
            )
            assert messages["items"] == []
            assert (
                check(await client.get(f"/api/v1/profiles/{pid}?version=1"), 200, "Profile")[
                    "version"
                ]
                == 1
            )

    asyncio.run(run())


def test_model_capability_validation_and_frozen_model():
    class SpyIntake(FakeIntake):
        calls = []

        async def extract_job(self, raw_text, company_context, *, context):
            self.calls.append(context.model_id)
            return await super().extract_job(raw_text, company_context, context=context)

    async def run():
        models = ModelList(
            default_model_id="chat-only",
            items=[
                Model(
                    id="chat-only",
                    display_name="fake",
                    provider="fake",
                    capabilities=["profile_chat"],
                )
            ],
        )
        catalog = FakeModelCatalog(models)
        app = app_for(catalog=catalog)
        async with clients(app) as (client,):
            await session(client)
            for model in ("unknown", "chat-only"):
                check(
                    await post(client, "/api/v1/jobs", {**JOB, "model_id": model}),
                    422,
                    code="MODEL_UNAVAILABLE",
                )
            assert not app.state.platform.repo.tasks
        executor = FakeTaskExecutor(gate=asyncio.Event())
        spy = SpyIntake()
        catalog = FakeModelCatalog()
        app = app_for(executor=executor, catalog=catalog, intake=spy)
        async with clients(app) as (client,):
            await session(client)
            a = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            b = check(
                await post(client, "/api/v1/jobs", {**JOB, "model_id": "demo-model-b"}),
                202,
                "TaskAccepted",
            )
            catalog.models.default_model_id = "demo-model-b"
            executor.gate.set()
            assert (await poll(client, a["task_id"]))[0]["model_id"] == "demo-model-a"
            assert (await poll(client, b["task_id"]))[0]["model_id"] == "demo-model-b"
            assert sorted(spy.calls) == ["demo-model-a", "demo-model-b"]

    asyncio.run(run())


def test_disabled_after_enqueue_does_not_fallback():
    async def run():
        executor = FakeTaskExecutor(gate=asyncio.Event())
        catalog = FakeModelCatalog()
        app = app_for(executor=executor, catalog=catalog)
        async with clients(app) as (client,):
            await session(client)
            accepted = check(
                await post(client, "/api/v1/jobs", {**JOB, "model_id": "demo-model-b"}),
                202,
                "TaskAccepted",
            )
            catalog.disabled.add("demo-model-b")
            executor.gate.set()
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["error"]["code"] == "MODEL_UNAVAILABLE"
            assert task["model_id"] == "demo-model-b" and not app.state.platform.repo.jobs

    asyncio.run(run())


@pytest.mark.parametrize("failed_stage,expected", [("report", "score_only"), ("scoring", "failed")])
def test_partial_score_only_export_and_frozen_history(failed_stage, expected):
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            result = await graph(client)
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            jid = task["result"]["resource_id"]
            check(await client.post(f"/api/v1/jobs/{jid}/confirm", json={"version": 1}), 200, "Job")
            app.state.platform.executor.failures[f"{failed_stage}:{jid}"] = "MODEL_TIMEOUT"
            body = {**result["body"], "jobs": [*result["body"]["jobs"], {"id": jid, "version": 1}]}
            accepted = check(
                await post(client, "/api/v1/diagnoses", body), 202, "DiagnosisAccepted"
            )
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "partial" and task["result"] and task["error"] is None
            did = accepted["diagnosis_id"]
            diagnosis = check(await client.get(f"/api/v1/diagnoses/{did}"), 200, "Diagnosis")
            assert [i["status"] for i in diagnosis["items"]] == ["succeeded", expected]
            assert bool(diagnosis["items"][1]["score_result"]) == (expected == "score_only")
            assert diagnosis["items"][1]["report"] is None
            assert "MODEL_TIMEOUT" in (await client.get(f"/api/v1/diagnoses/{did}/export")).text
            pid = result["profile"]["id"]
            check(
                await client.put(
                    f"/api/v1/profiles/{pid}",
                    json={"base_version": 1, "content": PROFILE["content"]},
                ),
                200,
                "Profile",
            )
            assert (
                check(await client.get(f"/api/v1/diagnoses/{did}"), 200, "Diagnosis") == diagnosis
            )

    asyncio.run(run())


def test_reject_unconfirmed_duplicate_and_unscorable_atomically():
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            result = await graph(client)
            body = result["body"]
            before = len(app.state.platform.repo.tasks)
            duplicates = {**body, "jobs": [body["jobs"][0], {**body["jobs"][0], "version": 2}]}
            # Both versions must exist before testing the business duplicate guard.
            job = result["job"]
            jid = job["id"]
            check(
                await client.put(
                    f"/api/v1/jobs/{jid}",
                    json={
                        "base_version": 1,
                        "raw_text": job["raw_text"],
                        "content": job["content"],
                    },
                ),
                200,
                "Job",
            )
            check(await post(client, "/api/v1/diagnoses", duplicates), 422, code="VALIDATION_ERROR")
            unconfirmed = {**body, "jobs": [{"id": jid, "version": 2}]}
            check(
                await post(client, "/api/v1/diagnoses", unconfirmed),
                422,
                code="UNCONFIRMED_VERSION",
            )
            no_requirements = copy.deepcopy(job["content"])
            no_requirements["requirements"] = []
            check(
                await client.put(
                    f"/api/v1/jobs/{jid}",
                    json={
                        "base_version": 2,
                        "raw_text": job["raw_text"],
                        "content": no_requirements,
                    },
                ),
                200,
                "Job",
            )
            check(await client.post(f"/api/v1/jobs/{jid}/confirm", json={"version": 3}), 200, "Job")
            check(
                await post(
                    client, "/api/v1/diagnoses", {**body, "jobs": [{"id": jid, "version": 3}]}
                ),
                422,
                code="NO_SCORABLE_REQUIREMENTS",
            )
            assert len(app.state.platform.repo.tasks) == before

    asyncio.run(run())


def test_multipart_upload_bounds_and_terminal_result():
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)

            async def upload(data, media="application/pdf", extra=None):
                return await client.post(
                    "/api/v1/documents",
                    files={"file": ("synthetic.pdf", data, media)},
                    data={"model_id": "demo-model-a", **(extra or {})},
                    headers={"Idempotency-Key": str(uuid4())},
                )

            accepted = check(
                await upload(b"%PDF-1.7\n% synthetic upload stub"), 202, "TaskAccepted"
            )
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "succeeded"
            profile = check(
                await client.get(f"/api/v1/profiles/{task['result']['resource_id']}"),
                200,
                "Profile",
            )
            assert "未执行真实文档解析" in profile["content"]["overview"]
            check(await upload(b"not a PDF"), 415, code="UNSUPPORTED_FILE_TYPE")
            check(await upload(b"%PDF-" + b"x" * (10 * 1024 * 1024)), 413, code="FILE_TOO_LARGE")
            check(await upload(b"%PDF-" + b"x" * (11 * 1024 * 1024)), 413, code="FILE_TOO_LARGE")
            check(
                await upload(b"%PDF-", extra={"unexpected": "synthetic-private-marker"}),
                422,
                code="VALIDATION_ERROR",
            )
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
            accepted = check(
                await upload(
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                202,
                "TaskAccepted",
            )
            assert (await poll(client, accepted["task_id"]))[0]["status"] == "succeeded"

    asyncio.run(run())


def test_origin_preflight_and_missing_origin():
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            response = await client.options(
                "/api/v1/session",
                headers={
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type,Idempotency-Key",
                },
            )
            assert (
                response.status_code == 200
                and response.headers["Access-Control-Allow-Origin"] == ORIGIN
            )
            check(
                await client.options(
                    "/api/v1/session",
                    headers={
                        "Origin": "https://evil.test",
                        "Access-Control-Request-Method": "POST",
                    },
                ),
                403,
                code="ORIGIN_FORBIDDEN",
            )
            await session(client)
            response = await post(client, "/api/v1/jobs", {**JOB, "model_id": "missing"})
            check(response, 422, code="MODEL_UNAVAILABLE")
            assert response.headers["Access-Control-Allow-Credentials"] == "true"
            client.headers.pop("Origin")
            check(await post(client, "/api/v1/jobs", JOB), 403, code="ORIGIN_FORBIDDEN")

    asyncio.run(run())


def test_full_generated_contract_has_no_pending_operations():
    result = compare_routes(DESIGN, app_for().openapi())
    assert result["pending"] == [] and len(result["implemented"]) == 18
