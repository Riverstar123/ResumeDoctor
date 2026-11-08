"""Durable optional advice acceptance using local SQLite and synthetic providers."""

# ruff: noqa: F811 -- imported SQLite fixtures are injected by pytest.

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select, update

from app.contracts import EnhancementCreate
from app.database import create_app
from app.llm import FakeModelDirectory
from app.platform.demo_gateway import JOB_TEXTS, IntegrationFakeGateway
from app.platform.errors import PlatformError
from app.platform.jobs.store import JobStore
from app.platform.jobs.worker import create_worker
from app.platform.repositories import schema as db
from app.platform.repositories.postgres import PostgreSQLRepository
from app.platform.repositories.sqlite import SQLiteRepository, initialize_sqlite
from app.settings import Settings

from .test_api import check, post, session
from .test_enhancement_acceptance import ObservedReporting
from .test_int02 import client_for, diagnose, prepared_job, prepared_profile
from .test_sqlite import repo, url  # noqa: F401 -- reusable database fixtures


def open_repository(url):
    return PostgreSQLRepository(url) if url.startswith("postgresql") else SQLiteRepository(url)


def race_requests(url, actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        repository = open_repository(url)
        try:
            barrier.wait(timeout=10)
            try:
                return action(repository)
            except PlatformError as error:
                return error.info.code
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(invoke, actions))


def test_sql_base_and_advice_survive_restart_rejection_and_duplicate_requests(repo, url, tmp_path):
    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    directory = FakeModelDirectory()
    gateway = IntegrationFakeGateway(directory)
    reporting = ObservedReporting()
    app = create_app(settings, repository=repo, gateway=gateway)
    worker = create_worker(settings, repository=repo, gateway=gateway, reporting=reporting)

    async def run():
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker, JOB_TEXTS[0])
            diagnosis = await diagnose(client, worker, profile, [job])
            assert diagnosis["model_id"] is None and reporting.calls == 0
            item = diagnosis["items"][0]
            assert item["report_template_version"] == "base-report-v1"
            base = deepcopy(item["report"])
            frozen_time = repo.clock()
            repo.clock = lambda: frozen_time
            endpoint = f"/api/v1/diagnoses/{diagnosis['id']}"
            advice_url = f"{endpoint}/items/{item['id']}/enhancements"
            body = EnhancementCreate(model_id="demo-model-a")
            metadata = directory.resolve("demo-model-a", "diagnosis_report", repo.now()).model_dump(
                mode="json"
            )
            requests = race_requests(
                url,
                [
                    lambda r: r.enhancement_create(
                        sid, diagnosis["id"], item["id"], body, str(uuid4()), metadata
                    )
                ]
                * 4,
            )
            assert len({request.task_id for request in requests}) == 1
            with repo.engine.begin() as connection:
                connection.execute(
                    update(db.enhancements)
                    .where(db.enhancements.c.item_id == item["id"])
                    .values(created_at=frozen_time)
                )
            assert reporting.calls == 0
            busy = await post(client, advice_url, {"model_id": "demo-model-b"})
            assert busy.status_code == 409 and busy.json()["error"]["code"] == "ENHANCEMENT_BUSY"
            assert await worker.run_once()
            current = check(await client.get(endpoint), 200, "Diagnosis")["items"][0]
            assert current["enhancement"]["status"] == "succeeded", current
            assert current["report"]["summary"] == base["summary"]
            assert current["report"]["actions"] and reporting.calls == 1
            saved = deepcopy(current["report"])
            repeated = check(await post(client, advice_url, body.model_dump()), 202, "TaskAccepted")
            assert repeated["task_id"] == requests[0].task_id
            reporting.fail = True
            fail = check(
                await post(client, advice_url, {"model_id": "demo-model-b"}), 202, "TaskAccepted"
            )
            assert await worker.run_once()
            current = check(await client.get(endpoint), 200, "Diagnosis")["items"][0]
            assert current["report"] == saved and current["status"] == "succeeded"
            assert current["enhancement"]["status"] == "failed"
            assert current["enhancement_history"][0]["model_metadata"] is not None
            assert current["enhancement_history"][1]["model_metadata"] is None
            assert reporting.calls == 2
            again = check(
                await post(client, advice_url, {"model_id": "demo-model-b"}), 202, "TaskAccepted"
            )
            assert again == fail
            other = open_repository(url)
            try:
                restarted = create_app(settings, repository=other, gateway=gateway)
                async with client_for(restarted, cookies=client.cookies) as fresh:
                    assert check(await fresh.get(endpoint), 200, "Diagnosis")["items"][0] == current
                    assert (await fresh.get(endpoint + "/export")).status_code == 200
            finally:
                other.close()
            repo.revoke(sid)
            with repo.engine.connect() as connection:
                assert not connection.execute(select(db.enhancements)).first()

    asyncio.run(run())


def test_expired_enhancement_lease_is_not_reissued_or_allowed_to_fail_base(repo, url, tmp_path):
    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    directory = FakeModelDirectory()
    gateway = IntegrationFakeGateway(directory)
    app = create_app(settings, repository=repo, gateway=gateway)
    worker = create_worker(settings, repository=repo, gateway=gateway)

    async def run():
        async with client_for(app) as client:
            await session(client)
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker, JOB_TEXTS[0])
            diagnosis = await diagnose(client, worker, profile, [job])
            item = diagnosis["items"][0]
            endpoint = f"/api/v1/diagnoses/{diagnosis['id']}"
            check(
                await post(
                    client,
                    f"{endpoint}/items/{item['id']}/enhancements",
                    {"model_id": "demo-model-a"},
                ),
                202,
                "TaskAccepted",
            )
            store = JobStore(repo)
            lease = store.claim()
            assert lease.input["mode"] == "enhancement"
            now = repo.clock()
            repo.clock = lambda: now + timedelta(seconds=61)
            assert store.reap() == 1
            assert store.claim() is None
            result = check(await client.get(endpoint), 200, "Diagnosis")
            assert result["status"] == "succeeded"
            assert result["items"][0]["report"] == item["report"]
            assert result["items"][0]["enhancement"]["status"] == "failed"

    asyncio.run(run())


def test_explicit_v1_to_v2_upgrade_preserves_existing_resources(repo, url):
    sid = repo.create_session()[0].public.id
    with repo.engine.begin() as connection:
        db.enhancements.drop(connection)
        connection.exec_driver_sql("PRAGMA user_version=1")
    initialize_sqlite(url)
    initialize_sqlite(url)
    other = SQLiteRepository(url)
    try:
        assert other.active(sid).public.id == sid
        with other.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == 2
            assert not connection.execute(select(db.enhancements)).first()
    finally:
        other.close()


def test_legacy_report_cannot_start_paid_enhancement(repo, url, tmp_path):
    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    gateway = IntegrationFakeGateway(FakeModelDirectory())
    app = create_app(settings, repository=repo, gateway=gateway)
    reporting = ObservedReporting()
    worker = create_worker(settings, repository=repo, gateway=gateway, reporting=reporting)

    async def run():
        async with client_for(app) as client:
            await session(client)
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker, JOB_TEXTS[0])
            diagnosis = await diagnose(client, worker, profile, [job])
            item = diagnosis["items"][0]
            with repo.engine.begin() as connection:
                task = (
                    connection.execute(
                        select(db.tasks).where(db.tasks.c.id == diagnosis["task_id"])
                    )
                    .mappings()
                    .one()
                )
                legacy = dict(task["input"])
                legacy.pop("report_template_version")
                connection.execute(
                    update(db.tasks)
                    .where(db.tasks.c.id == diagnosis["task_id"])
                    .values(input=legacy)
                )
            response = await post(
                client,
                f"/api/v1/diagnoses/{diagnosis['id']}/items/{item['id']}/enhancements",
                {"model_id": "demo-model-a"},
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "LEGACY_REPORT_REQUIRES_BASE"
            assert reporting.calls == 0
            with repo.engine.connect() as connection:
                assert not connection.execute(select(db.enhancements)).first()
                assert not connection.execute(
                    select(db.tasks).where(db.tasks.c.status == "queued")
                ).first()

    asyncio.run(run())


def test_queued_enhancement_from_old_policy_fails_before_provider_call(repo, url, tmp_path):
    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    gateway = IntegrationFakeGateway(FakeModelDirectory())
    app = create_app(settings, repository=repo, gateway=gateway)
    reporting = ObservedReporting()
    worker = create_worker(settings, repository=repo, gateway=gateway, reporting=reporting)

    async def run():
        async with client_for(app) as client:
            await session(client)
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker, JOB_TEXTS[0])
            diagnosis = await diagnose(client, worker, profile, [job])
            item = diagnosis["items"][0]
            endpoint = f"/api/v1/diagnoses/{diagnosis['id']}"
            task = check(
                await post(
                    client,
                    f"{endpoint}/items/{item['id']}/enhancements",
                    {"model_id": "demo-model-a"},
                ),
                202,
                "TaskAccepted",
            )
            with repo.engine.begin() as connection:
                payload = dict(
                    connection.execute(
                        select(db.tasks.c.input).where(db.tasks.c.id == task["task_id"])
                    ).scalar_one()
                )
                payload["policy_version"] = "old-policy"
                connection.execute(
                    update(db.tasks).where(db.tasks.c.id == task["task_id"]).values(input=payload)
                )
            assert await worker.run_once()
            current = check(await client.get(endpoint), 200, "Diagnosis")["items"][0]
            assert current["enhancement"]["status"] == "failed"
            assert current["enhancement"]["error"]["code"] == "ENHANCEMENT_POLICY_CHANGED"
            assert current["status"] == "succeeded" and current["report"] == item["report"]
            assert reporting.calls == 0

    asyncio.run(run())


def test_identical_enhancement_replays_before_model_changes_and_busy(repo, url, tmp_path):
    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    gateway = IntegrationFakeGateway(FakeModelDirectory())
    app = create_app(settings, repository=repo, gateway=gateway)
    worker = create_worker(settings, repository=repo, gateway=gateway)

    async def run():
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            profile = await prepared_profile(client, worker)
            job = await prepared_job(client, worker, JOB_TEXTS[0])
            diagnosis = await diagnose(client, worker, profile, [job])
            item = diagnosis["items"][0]
            endpoint = f"/api/v1/diagnoses/{diagnosis['id']}/items/{item['id']}/enhancements"
            requirement_ids = [r["id"] for r in job["content"]["requirements"] if not r["ignored"]]
            assert len(requirement_ids) > 1
            body = {"model_id": "demo-model-a", "requirement_ids": requirement_ids}
            key = str(uuid4())
            accepted = check(await post(client, endpoint, body, key=key), 202, "TaskAccepted")
            reordered = {**body, "requirement_ids": list(reversed(requirement_ids))}
            assert (
                check(await post(client, endpoint, reordered, key=key), 202, "TaskAccepted")
                == accepted
            )
            platform = app.state.platform
            original = platform._snapshot
            changed = original(body["model_id"], "diagnosis")
            changed["gateway_config_version"] = "new-mapping"
            platform._snapshot = lambda *args: changed
            assert (
                check(await post(client, endpoint, body, key=key), 202, "TaskAccepted") == accepted
            )
            assert (await post(client, endpoint, body)).status_code == 409

            def unavailable(*args):
                raise PlatformError(422, "MODEL_UNAVAILABLE", "disabled")

            platform._snapshot = unavailable
            assert (
                check(await post(client, endpoint, body, key=key), 202, "TaskAccepted") == accepted
            )
            assert (await post(client, endpoint, body)).status_code == 422
            assert (await post(client, endpoint, {"model_id": "demo-model-b"}, key=key)).json()[
                "error"
            ]["code"] == "IDEMPOTENCY_CONFLICT"
            # Recheck inside the transaction must also precede configuration resolution.
            replay = repo.enhancement_create(
                sid, diagnosis["id"], item["id"], EnhancementCreate(**body), key, unavailable
            )
            assert replay.task_id == accepted["task_id"]
            with repo.engine.connect() as connection:
                assert (
                    len(
                        connection.execute(
                            select(db.enhancements).where(db.enhancements.c.item_id == item["id"])
                        ).all()
                    )
                    == 1
                )

    asyncio.run(run())
