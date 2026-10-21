"""Review regressions using a live HTTP server and the real PostgreSQL pool.

Run only against RD_TEST_DATABASE_URL's disposable, migrated PostgreSQL database.
The live server uses one asyncio loop. Database waits are observed in
pg_stat_activity before liveness checks; releasing a lock always happens in finally.
"""

import asyncio
import multiprocessing
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Thread
from uuid import uuid4

import anyio
import httpx
import pytest
import uvicorn

sa = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text  # noqa: E402

from app.database import create_app  # noqa: E402
from app.platform.repositories import PostgreSQLRepository  # noqa: E402
from app.settings import Settings  # noqa: E402
from tests.platform import test_postgres as dbtest  # noqa: E402

engine, repo, sid, upload_dir = dbtest.engine, dbtest.repo, dbtest.sid, dbtest.upload_dir
counts, profile, profile_content, snapshot = (
    dbtest.counts,
    dbtest.profile,
    dbtest.profile_content,
    dbtest.snapshot,
)


@contextmanager
def live_server(app):
    """Bind an actual localhost socket; never replace HTTP with an ASGI transport."""
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def measured_lifespan(instance):
        async with original_lifespan(instance):
            instance.state.server_loop = asyncio.get_running_loop()
            # Database waits get two dedicated workers; the global pool has only
            # one token, so the thread probe also detects accidental pool sharing.
            anyio.to_thread.current_default_thread_limiter().total_tokens = 1
            instance.state.platform._io_limiter = anyio.CapacityLimiter(2)
            yield

    app.router.lifespan_context = measured_lifespan

    @app.get("/__test_thread_probe")
    async def global_thread_probe():
        return await anyio.to_thread.run_sync(lambda: {"status": "global-thread-available"})

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    host, port = listener.getsockname()
    config = uvicorn.Config(app, log_level="critical", lifespan="on", access_log=False)
    server = uvicorn.Server(config)
    worker = Thread(target=lambda: asyncio.run(server.serve(sockets=[listener])), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "The real HTTP server did not start"
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        assert not worker.is_alive(), (
            "Live HTTP server failed to stop after database locks released"
        )


def wait_for_pg_lock(engine, minimum=1):
    with engine.connect() as connection:
        app_name = connection.scalar(text("SHOW application_name"))
    deadline = time.monotonic() + 10
    blocked = 0
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            blocked = connection.scalar(
                text("""SELECT count(*) FROM pg_stat_activity
                    WHERE application_name=:app AND state='active'
                      AND wait_event_type='Lock' AND pid<>pg_backend_pid()"""),
                {"app": app_name},
            )
        if blocked >= minimum:
            return
        time.sleep(0.01)
    pytest.fail(f"Expected {minimum} active PostgreSQL lock waits; observed {blocked}")


@pytest.mark.parametrize("stage", ["resource", "authenticate", "prune", "sweep", "saturated"])
def test_live_http_stays_responsive_during_database_wait(
    repo, sid, engine, upload_dir, monkeypatch, stage
):
    import app.main

    # Use the actual periodic entry point, with a short interval only in this test.
    monkeypatch.setattr(
        app.main, "CLEANUP_INTERVAL_SECONDS", 0.05 if stage == "sweep" else 60, raising=False
    )
    _, token = repo.create_session()
    sid = repo.authenticate(token).public.id
    p = profile(repo, sid)
    other_session, other_token = repo.create_session()
    other_profile = profile(repo, other_session.public.id)
    second = profile(repo, sid) if stage == "saturated" else None
    settings = Settings(_env_file=None, upload_dir=upload_dir)
    app = create_app(settings, repository=repo)
    # Force prune/sweep to visit a specific expired key, leaving the session live.
    if stage in {"prune", "sweep"}:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE idempotency_keys SET created_at=:old WHERE session_id=:sid"),
                {"old": repo.clock() - timedelta(hours=25), "sid": sid},
            )
    with engine.begin() as blocker:
        if stage in {"resource", "saturated"}:
            ids = [p.id] + ([second.id] if second else [])
            for pid in ids:
                blocker.execute(
                    text("SELECT id FROM profiles WHERE id=:id FOR UPDATE"), {"id": pid}
                )
        elif stage == "authenticate":
            blocker.execute(text("SELECT id FROM sessions WHERE id=:id FOR UPDATE"), {"id": sid})
        else:
            blocker.execute(
                text("SELECT key FROM idempotency_keys WHERE session_id=:sid FOR UPDATE"),
                {"sid": sid},
            )
        with live_server(app) as base:
            with ThreadPoolExecutor(max_workers=3) as clients:
                requests = []

                def request_profile(pid):
                    with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
                        if stage in {"resource", "saturated"}:
                            return client.put(
                                f"/api/v1/profiles/{pid}",
                                headers={
                                    "Origin": "http://localhost:5173",
                                    "Cookie": f"rd_session={token}",
                                },
                                json={
                                    "base_version": 1,
                                    "content": profile_content(
                                        "synthetic concurrent edit"
                                    ).model_dump(mode="json"),
                                },
                            )
                        return client.get(
                            f"/api/v1/profiles/{pid}", headers={"Cookie": f"rd_session={token}"}
                        )

                try:
                    if stage != "sweep":
                        requests.append(clients.submit(request_profile, p.id))
                        if second:
                            requests.append(clients.submit(request_profile, second.id))
                    wait_for_pg_lock(engine, 2 if second else 1)
                    # This callback can execute only if the same asyncio loop that
                    # serves HTTP is alive while the database is still locked.
                    heartbeat = Event()
                    app.state.server_loop.call_soon_threadsafe(heartbeat.set)
                    assert heartbeat.wait(timeout=1.5), (
                        "Synchronous PostgreSQL I/O blocked the event loop"
                    )
                    with httpx.Client(base_url=base, timeout=1.5, trust_env=False) as client:
                        response = client.get("/healthz")
                        assert response.status_code == 200 and response.json() == {"status": "ok"}
                        probe = client.get("/__test_thread_probe")
                        assert probe.status_code == 200
                        if stage in {"resource", "authenticate"}:
                            unrelated = client.get(
                                f"/api/v1/profiles/{other_profile.id}",
                                headers={"Cookie": f"rd_session={other_token}"},
                            )
                            assert unrelated.status_code == 200
                            assert unrelated.json()["id"] == other_profile.id
                    assert all(not request.done() for request in requests)
                finally:
                    # Release before waiting for HTTP futures or server shutdown.
                    blocker.commit()
                for request in requests:
                    assert request.result(timeout=10).status_code == 200


@pytest.fixture
def default_pool_repo(upload_dir):
    url = os.environ.get("RD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("RD_TEST_DATABASE_URL is required for PostgreSQL acceptance")
    parsed = sa.engine.make_url(url)
    assert parsed.get_backend_name() == "postgresql" and "test" in parsed.database.lower()
    # Keep SQLAlchemy's production defaults, shrinking only timeout for a bounded
    # regression. Raising pool capacity would hide the nested-checkout defect.
    pool = create_engine(url, pool_timeout=1.5, hide_parameters=True)
    assert pool.pool.size() == 5 and pool.pool._max_overflow == 10
    repository = PostgreSQLRepository(pool)
    owned_sessions = []
    create_session = repository.create_session

    def tracked_session():
        record, token = create_session()
        owned_sessions.append(record.public.id)
        return record, token

    repository.create_session = tracked_session
    yield repository
    for owned_sid in owned_sessions:
        repository.revoke(owned_sid)
    repository.retry_file_cleanup(upload_dir)
    pool.dispose()


def upload(repository, sid, directory, key=None):
    return repository.document_create(
        sid,
        b"%PDF-1.4\nsynthetic concurrent upload\n%%EOF\n",
        "application/pdf",
        "demo-model-a",
        key or uuid4().hex,
        snapshot(repository),
        directory,
    )


def test_fifteen_uploads_do_not_need_a_sixteenth_pool_connection(
    default_pool_repo, upload_dir, monkeypatch
):
    repository = default_pool_repo
    sessions = [repository.create_session()[0].public.id for _ in range(15)]
    reached = Barrier(15)
    original_claim = repository._claim

    def synchronized_claim(connection, sid, key, operation, body, resource_type, resource_id):
        cached = original_claim(connection, sid, key, operation, body, resource_type, resource_id)
        if operation == "document" and cached is None:
            # Every caller owns its outer transaction before any proceeds. A
            # nested checkout now cannot succeed with the default 15-connection cap.
            reached.wait(timeout=10)
        return cached

    monkeypatch.setattr(repository, "_claim", synchronized_claim)

    def attempt(sid):
        try:
            return upload(repository, sid, upload_dir)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=15) as workers:
        outcomes = list(workers.map(attempt, sessions))
    errors = [type(outcome).__name__ for outcome in outcomes if isinstance(outcome, Exception)]
    assert not errors, f"Concurrent upload errors at default pool capacity: {errors}"
    assert len({outcome.task_id for outcome in outcomes}) == 15
    assert sum(counts(repository.engine, sid)["tasks"] for sid in sessions) == 15
    assert sum(counts(repository.engine, sid)["documents"] for sid in sessions) == 15
    files = [path.name for path in upload_dir.iterdir()]
    assert len(files) == 15
    with repository.engine.connect() as connection:
        rows = connection.execute(text("SELECT storage_key FROM file_cleanup")).scalars().all()
    assert len(rows) == 15 and set(files) == set(rows)


def test_concurrent_same_key_upload_has_one_file_task_document_and_cleanup(repo, sid, upload_dir):
    barrier, key = Barrier(4), uuid4().hex

    def attempt():
        barrier.wait(timeout=10)
        return upload(repo, sid, upload_dir, key)

    with ThreadPoolExecutor(max_workers=4) as workers:
        outcomes = list(workers.map(lambda _: attempt(), range(4)))
    assert len({outcome.task_id for outcome in outcomes}) == 1
    after = counts(repo.engine, sid)
    assert after["tasks"] == after["documents"] == after["idempotency_keys"] == 1
    files = [path.name for path in upload_dir.iterdir()]
    assert len(files) == 1
    with repo.engine.connect() as connection:
        rows = connection.execute(text("SELECT storage_key FROM file_cleanup")).scalars().all()
    assert set(files).issubset(rows)
    # The database is dedicated to these tests; no unused reservations may remain.
    assert len(rows) == 1


def test_upload_rollback_keeps_cleanup_for_an_unlink_failure(repo, sid, upload_dir, monkeypatch):
    before = counts(repo.engine, sid)

    def failure(*args, **kwargs):
        raise RuntimeError("synthetic transaction failure")

    original_unlink = Path.unlink

    def unlink_failure(path, *args, **kwargs):
        if path.parent == upload_dir:
            raise OSError("synthetic cleanup failure")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(repo, "_new_task", failure)
        patch.setattr(Path, "unlink", unlink_failure)
        with pytest.raises(RuntimeError, match="synthetic transaction failure"):
            upload(repo, sid, upload_dir)
    assert counts(repo.engine, sid) == before
    files = [path.name for path in upload_dir.iterdir()]
    assert len(files) == 1
    with repo.engine.connect() as connection:
        keys = connection.execute(text("SELECT storage_key FROM file_cleanup")).scalars().all()
    assert files[0] in keys
    repo.clock = lambda: datetime.now(UTC) + timedelta(days=2)
    repo.retry_file_cleanup(upload_dir)
    assert not list(upload_dir.iterdir())


def crash_after_file_write(database_url, sid, upload_dir):
    """A genuine process exit bypasses exception/finally cleanup and closes SQL sockets."""
    child_repo = PostgreSQLRepository(database_url)

    def crash(*args, **kwargs):
        os._exit(23)

    child_repo._new_task = crash
    upload(child_repo, sid, upload_dir)


def test_crash_after_file_write_leaves_durable_orphan_handoff(repo, sid, upload_dir):
    process = multiprocessing.get_context("spawn").Process(
        target=crash_after_file_write,
        args=(os.environ["RD_TEST_DATABASE_URL"], sid, upload_dir),
    )
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("Crash reproduction child failed to exit")
    assert process.exitcode == 23
    after = counts(repo.engine, sid)
    assert after["tasks"] == after["documents"] == after["idempotency_keys"] == 0
    files = [path.name for path in upload_dir.iterdir()]
    assert len(files) == 1
    with repo.engine.connect() as connection:
        keys = connection.execute(text("SELECT storage_key FROM file_cleanup")).scalars().all()
    assert files[0] in keys
    original_clock = repo.clock
    repo.clock = lambda: original_clock() + timedelta(days=2)
    repo.retry_file_cleanup(upload_dir)
    assert not list(upload_dir.iterdir())
