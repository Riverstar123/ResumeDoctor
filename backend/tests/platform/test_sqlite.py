"""SQLite-specific durability/concurrency acceptance; all provider outputs are synthetic."""

# ruff: noqa: E402 -- keep database dependencies optional for the minimal test suite.

import asyncio
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.contracts import ProfileCreate
from app.database import create_app
from app.llm import FakeModelDirectory
from app.platform.demo_gateway import IntegrationFakeGateway
from app.platform.errors import PlatformError
from app.platform.jobs.store import JobStore, LeaseLost
from app.platform.jobs.worker import create_worker
from app.platform.repositories import database_repository
from app.platform.repositories import schema as db
from app.platform.repositories.sqlite import SQLiteRepository, initialize_sqlite
from app.settings import Settings

from .test_api import check, session
from .test_int02 import (
    client_for,
    diagnose,
    prepared_job,
    prepared_profile,
)
from .test_postgres import profile_content, snapshot, task


@pytest.fixture
def url(tmp_path):
    url = f"sqlite:///{tmp_path / 'acceptance.sqlite3'}"
    initialize_sqlite(url)
    return url


@pytest.fixture
def repo(url):
    repository = SQLiteRepository(url)
    yield repository
    repository.close()


def test_explicit_initialization_schema_guards_and_wal(tmp_path, url):
    empty = f"sqlite:///{tmp_path / 'empty.sqlite3'}"
    with pytest.raises(ValueError, match="Initialize"):
        SQLiteRepository(empty)
    for invalid in ("sqlite:///:memory:", "sqlite:///file:test?mode=memory", "sqlite:///"):
        with pytest.raises(ValueError):
            initialize_sqlite(invalid)
    initialize_sqlite(url)
    repository = database_repository(url)
    try:
        with repository.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            connection.exec_driver_sql("PRAGMA user_version=999")
            connection.commit()
        with pytest.raises(ValueError, match="Unsupported"):
            initialize_sqlite(url)
    finally:
        repository.close()


@pytest.mark.parametrize("route", ["chat", "upload"])
def test_http_business_flow_five_jobs_export_restart_and_revoke(repo, url, tmp_path, route):
    from app.platform.demo_gateway import JOB_TEXTS

    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    gateway = IntegrationFakeGateway(FakeModelDirectory())
    app = create_app(settings, repository=repo, gateway=gateway)
    worker = create_worker(settings, repository=repo, gateway=gateway)

    async def run():
        async with client_for(app) as client:
            sid = (await session(client))["id"]
            profile = await prepared_profile(client, worker, route)
            jobs = [await prepared_job(client, worker, raw) for raw in JOB_TEXTS]
            diagnosis = await diagnose(client, worker, profile, jobs)
            assert [item["score_result"]["score"] for item in diagnosis["items"]] == [
                66.7,
                0,
                100,
                50,
                0,
            ]
            path = f"/api/v1/diagnoses/{diagnosis['id']}"
            exported = await client.get(path + "/export")
            assert exported.status_code == 200 and profile["id"] in exported.text
            other = SQLiteRepository(url)
            try:
                restarted = create_app(settings, repository=other, gateway=gateway)
                async with client_for(restarted, cookies=client.cookies) as refreshed:
                    assert check(await refreshed.get(path), 200, "Diagnosis") == diagnosis
                    assert (await refreshed.get(path + "/export")).text == exported.text
                async with client_for(restarted) as stranger:
                    await session(stranger)
                    assert (await stranger.get(path)).status_code == 404
            finally:
                other.close()
            repo.revoke(sid)
            assert (await client.get(path)).status_code == 401
            with repo.engine.connect() as connection:
                for table in (
                    db.profiles,
                    db.profile_versions,
                    db.tasks,
                    db.diagnoses,
                    db.messages,
                ):
                    assert not connection.execute(
                        select(table).where(table.c.session_id == sid)
                    ).first()

    asyncio.run(run())


def race(url, actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        repository = SQLiteRepository(url)
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


def test_independent_connections_serialize_replay_edits_and_queue_limit(repo, url):
    sid = repo.create_session()[0].public.id
    body = ProfileCreate(content=profile_content())
    key = uuid4().hex
    profiles = race(url, [lambda r: r.profile_create(sid, body, key)] * 4)
    assert len({p.id for p in profiles}) == 1
    edits = race(
        url, [lambda r: r.append(r.profiles, profiles[0].id, sid, 1, content=body.content)] * 2
    )
    assert sum(isinstance(item, str) for item in edits) == 1
    tasks = race(url, [lambda r: task(r, sid)] * 4)
    assert tasks.count("RATE_LIMITED") == 2
    with repo.engine.connect() as connection:
        assert (
            len(connection.execute(select(db.tasks).where(db.tasks.c.session_id == sid)).all()) == 2
        )


def child_claim(url, now, gate, output, crash):
    repository = SQLiteRepository(url, clock=lambda: now)
    try:
        gate.wait(timeout=15)
        lease = JobStore(repository).claim()
        output.send(lease)
        if crash:
            os._exit(19)
    finally:
        repository.close()
        output.close()


def test_process_claim_crash_reclaim_and_fenced_old_result(repo, url):
    now = datetime.now(UTC)
    repo.clock = lambda: now
    sid = repo.create_session()[0].public.id
    accepted = task(repo, sid)
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    children, channels = [], []
    for _ in range(2):
        reader, writer = context.Pipe(duplex=False)
        child = context.Process(target=child_claim, args=(url, now, gate, writer, True))
        child.start()
        writer.close()
        children.append(child)
        channels.append(reader)
    gate.set()
    try:
        leases = []
        for channel in channels:
            assert channel.poll(20), "child failed to return its committed lease"
            leases.append(channel.recv())
        for child in children:
            child.join(timeout=10)
            assert not child.is_alive() and child.exitcode == 19
        assert sum(lease is not None for lease in leases) == 1
        old = next(lease for lease in leases if lease is not None)
        assert old.task_id == accepted.task_id
        assert JobStore(repo).claim() is None
        repo.clock = lambda: now + timedelta(seconds=61)
        resumed = JobStore(repo).claim()
        assert resumed.attempt == 2 and resumed.token != old.token
        with pytest.raises(LeaseLost):
            JobStore(repo).commit_job(
                old, {"title": "stale", "company_context": "", "requirements": []}
            )
        assert not JobStore(repo).heartbeat(old)
        assert JobStore(repo).heartbeat(resumed)
        repo.clock = lambda: now + timedelta(minutes=6)
        JobStore(repo).reap()
        assert repo.owned(repo.tasks, accepted.task_id, sid).value.error.code == "TASK_TIMEOUT"
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)
        for channel in channels:
            channel.close()


def test_immutable_versions_foreign_ownership_and_confirmation(repo):
    sid = repo.create_session()[0].public.id
    other = repo.create_session()[0].public.id
    profile = repo.profile_create(sid, ProfileCreate(content=profile_content()), uuid4().hex)
    with pytest.raises(IntegrityError):
        with repo.engine.begin() as connection:
            connection.execute(update(db.profile_versions).values(content={"overview": "tampered"}))
    with pytest.raises(IntegrityError):
        with repo.engine.begin() as connection:
            connection.execute(
                insert(db.profile_versions).values(
                    profile_id=profile.id,
                    session_id=other,
                    version=2,
                    content=profile.content.model_dump(mode="json"),
                    created_at=repo.clock(),
                )
            )
    repo.confirm(repo.profiles, profile.id, sid, 1)
    with pytest.raises(IntegrityError):
        with repo.engine.begin() as connection:
            connection.execute(update(db.profile_versions).values(confirmed_at=None))
    assert repo.version(repo.profiles, profile.id, sid).confirmed


def test_utc_expiry_and_durable_original_cleanup(repo, tmp_path):
    now = datetime(2026, 11, 1, tzinfo=UTC)
    repo.clock = lambda: now
    sid = repo.create_session()[0].public.id
    accepted = repo.document_create(
        sid,
        b"%PDF-synthetic",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        tmp_path,
    )
    with repo.engine.connect() as connection:
        document = connection.execute(select(db.documents)).mappings().one()
    assert (tmp_path / document["storage_key"]).is_file()
    assert repo.owned(repo.tasks, accepted.task_id, sid).value.status == "queued"
    repo.clock = lambda: now + timedelta(hours=24)
    assert repo.retry_file_cleanup(tmp_path) == 1
    assert not (tmp_path / document["storage_key"]).exists()
    repo.clock = lambda: now + timedelta(days=8)
    assert repo.cleanup_expired() == 1
    with pytest.raises(PlatformError):
        repo.active(sid)
