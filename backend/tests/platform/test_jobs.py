"""JOB-01 recovery acceptance on migrated, disposable PostgreSQL only.

The imported DB fixture never drops/truncates a database. Process tests use spawn,
independent engines and committed leases, so no inherited in-memory queue or lock
can accidentally satisfy recovery. All model and document inputs are synthetic.
"""

# ruff: noqa: F811 -- imported PostgreSQL fixtures are injected by pytest.

import asyncio
import multiprocessing
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text  # noqa: E402

from app.contracts import ErrorInfo  # noqa: E402
from app.platform.errors import PlatformError  # noqa: E402
from app.platform.repositories import PostgreSQLRepository  # noqa: E402

from .test_postgres import (  # noqa: E402
    counts,
    diagnosis_body,
    engine,  # noqa: F401
    job,
    job_content,
    profile,
    profile_content,
    repo,  # noqa: F401
    sid,  # noqa: F401
    snapshot,
    task,
    upload_dir,  # noqa: F401
)


class Clock:
    def __init__(self):
        self.value = datetime.now(UTC)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clock(repo):
    clock = Clock()
    repo.clock = clock
    return clock


@pytest.fixture
def store(repo):
    from app.platform.jobs.store import JobStore

    return JobStore(repo)


def raw_task(engine, tid):
    with engine.connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM tasks WHERE id=:id"), {"id": tid})
            .mappings()
            .one()
        )


def failure(code="PROVIDER_UNAVAILABLE"):
    return ErrorInfo(code=code, message="Synthetic controlled failure")


def prepared_diagnosis(repo, sid, number=2):
    p = profile(repo, sid)
    repo.confirm(repo.profiles, p.id, sid, p.version)
    jobs = [job(repo, sid) for _ in range(number)]
    for j in jobs:
        repo.confirm(repo.jobs, j.id, sid, j.version)
    return repo.diagnosis_create(sid, diagnosis_body(p, *jobs), uuid4().hex, snapshot(repo))


def score_for(work, index=0):
    from app.scoring import ScoringService

    calculator = ScoringService()
    j = work.jobs[index]
    assessments = calculator.assess_requirements(work.profile.content, j.content, "matcher-v1")
    return calculator.calculate_score(assessments, "coverage-v1")


def _child_claim(url, at, gate, connection, *, crash=False, commit=False):
    """Spawn target: deliberately construct a fresh Engine in each process."""
    from app.platform.jobs.store import JobStore

    database = create_engine(url, hide_parameters=True)
    try:
        repository = PostgreSQLRepository(database, clock=lambda: at)
        store = JobStore(repository)
        if gate is not None:
            assert gate.wait(15), "Parent did not release the process barrier"
        lease = store.claim()
        if commit and lease is not None:
            from app.contracts import ModelMetadata
            from app.platform.fakes import FakeIntake, FakeReporting
            from app.platform.jobs.worker import Worker
            from app.scoring import ScoringService

            class FrozenCatalog:
                def resolve(self, *args):
                    return ModelMetadata.model_validate(lease.model_snapshot)

            worker = Worker(
                store,
                intake=FakeIntake(),
                scoring=ScoringService(),
                reporting=FakeReporting(),
                catalog=FrozenCatalog(),
                upload_dir="unused",
            )
            asyncio.run(worker.execute(lease))
            saved = repository.owned(repository.tasks, lease.task_id, lease.session_id).value
            assert saved.status == "succeeded", saved
            connection.send(("committed", lease, saved.result.resource_id))
        else:
            connection.send(("claimed", lease))
        if crash:
            # The lease transaction has committed. Bypass finally/graceful cleanup.
            os._exit(19)
    except BaseException as error:
        connection.send(("error", type(error).__name__, str(error)))
    finally:
        connection.close()
        database.dispose()


def process_claim(engine, at, *, crash=False, commit=False):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_child_claim,
        args=(engine.url.render_as_string(hide_password=False), at, None, sender),
        kwargs={"crash": crash, "commit": commit},
    )
    process.start()
    sender.close()
    try:
        assert receiver.poll(20), "Worker process did not report its committed lease"
        answer = receiver.recv()
        process.join(20)
        assert not process.is_alive(), "Worker child did not exit"
        assert process.exitcode == (19 if crash else 0)
        assert answer[0] != "error", answer
        return answer
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        receiver.close()


def test_t14_two_independent_workers_compete_for_one_task(repo, sid, engine, clock):
    accepted = task(repo, sid)
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    workers = []
    receivers = []
    try:
        for _ in range(2):
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_child_claim,
                args=(
                    engine.url.render_as_string(hide_password=False),
                    clock(),
                    gate,
                    sender,
                ),
            )
            process.start()
            sender.close()
            workers.append(process)
            receivers.append(receiver)
        gate.set()
        outcomes = []
        for receiver in receivers:
            assert receiver.poll(20), "Independent worker did not finish claiming"
            answer = receiver.recv()
            assert answer[0] == "claimed", answer
            outcomes.append(answer[1])
        for process in workers:
            process.join(15)
            assert process.exitcode == 0
        winners = [lease for lease in outcomes if lease is not None]
        assert len(winners) == 1
        assert winners[0].task_id == accepted.task_id
        row = raw_task(engine, accepted.task_id)
        assert row["attempt"] == 1 and row["status"] == "running"
        assert row["lease_until"] - clock() == timedelta(seconds=60)
        assert row["deadline_at"] - row["created_at"] == timedelta(minutes=5)
    finally:
        for process in workers:
            if process.is_alive():
                process.kill()
                process.join(5)
        for receiver in receivers:
            receiver.close()


def test_t14_process_crash_reclaim_and_old_fencing_token(repo, sid, engine, clock, store):
    from app.platform.jobs.store import LeaseLost

    accepted = task(repo, sid)
    first = process_claim(engine, clock(), crash=True)[1]
    assert first.task_id == accepted.task_id
    assert store.claim() is None, "A live lease must not be stolen"
    clock.advance(61)
    result = process_claim(engine, clock(), commit=True)
    second, jid = result[1:]
    assert second.task_id == first.task_id and second.token != first.token
    assert second.attempt == 2
    with pytest.raises(LeaseLost):
        store.commit_job(first, job_content())
    with pytest.raises(LeaseLost):
        store.commit_job(second, job_content())
    row = raw_task(engine, accepted.task_id)
    assert row["status"] == "succeeded"
    assert row["result"]["resource_id"] == jid
    assert counts(engine, sid)["job_versions"] == 1
    assert counts(engine, sid)["jobs"] == 1


def test_t14_heartbeat_renewal_is_fenced_and_bounded(repo, sid, engine, clock, store):
    from app.platform.jobs.store import LeaseLost

    accepted = task(repo, sid)
    lease = store.claim()
    clock.advance(15)
    assert store.heartbeat(lease)
    row = raw_task(engine, accepted.task_id)
    assert row["heartbeat_at"] == clock()
    assert row["lease_until"] == clock() + timedelta(seconds=60)
    clock.advance(61)
    assert not store.heartbeat(lease)
    with pytest.raises(LeaseLost):
        store.commit_job(lease, job_content())
    takeover = store.claim()
    assert takeover.attempt == 2
    assert not store.heartbeat(lease)
    clock.advance(61)
    assert store.claim() is None
    row = raw_task(engine, accepted.task_id)
    assert row["attempt"] == 2 and row["status"] == "failed"
    assert counts(engine, sid)["jobs"] == 0


def test_total_deadline_also_expires_queued_tasks(repo, sid, engine, clock, store):
    accepted = task(repo, sid)
    clock.advance(301)
    assert store.claim() is None
    row = raw_task(engine, accepted.task_id)
    assert row["status"] == "failed" and row["attempt"] == 0
    assert row["error"]["code"] == "TASK_TIMEOUT"


def test_deadline_rejects_commit_even_if_lease_was_just_renewed(repo, sid, engine, clock, store):
    from app.platform.jobs.store import LeaseLost

    accepted = task(repo, sid)
    lease = store.claim()
    for _ in range(19):
        clock.advance(15)
        assert store.heartbeat(lease)
    clock.advance(15)
    assert not store.heartbeat(lease)
    with pytest.raises(LeaseLost):
        store.commit_job(lease, job_content())
    store.reap()
    row = raw_task(engine, accepted.task_id)
    assert row["status"] == "failed"
    assert row["error"]["code"] == "TASK_TIMEOUT"
    assert counts(engine, sid)["jobs"] == 0


def test_chat_result_is_atomic_and_cannot_overwrite_user_edit(repo, sid, engine, store):
    from app.platform.jobs.store import LeaseLost

    p = profile(repo, sid)
    accepted = repo.create_task(
        sid,
        "profile_chat",
        "demo-model-a",
        snapshot(repo),
        {"profile": {"id": p.id, "version": 1}, "base_version": 1, "content": "Python"},
        uuid4().hex,
        f"chat:{p.id}",
        {"content": "Python", "base_version": 1, "model_id": "demo-model-a"},
        profile_id=p.id,
    )
    lease = store.claim()
    edited = repo.append(repo.profiles, p.id, sid, 1, content=profile_content("user edit"))
    with pytest.raises(PlatformError) as caught:
        store.commit_chat(lease, profile_content("stale worker"), "Synthetic question")
    assert caught.value.info.code == "VERSION_CONFLICT"
    store.fail(lease, caught.value.info)
    assert repo.version(repo.profiles, p.id, sid) == edited
    assert counts(engine, sid)["profile_versions"] == 2
    assert counts(engine, sid)["messages"] == 0
    with pytest.raises(LeaseLost):
        store.commit_chat(lease, profile_content(), "duplicate")
    assert raw_task(engine, accepted.task_id)["status"] == "failed"


def test_chat_success_has_one_version_and_one_message_pair(repo, sid, engine, store):
    from app.platform.jobs.store import LeaseLost

    p = profile(repo, sid)
    accepted = repo.create_task(
        sid,
        "profile_chat",
        "demo-model-a",
        snapshot(repo),
        {"profile": {"id": p.id, "version": 1}, "base_version": 1, "content": "Python"},
        uuid4().hex,
        f"chat:{p.id}",
        {"content": "Python", "base_version": 1, "model_id": "demo-model-a"},
        profile_id=p.id,
    )
    lease = store.claim()
    saved = store.commit_chat(lease, profile_content("one successful turn"), "Synthetic question")
    assert saved.id == p.id and saved.version == 2
    with pytest.raises(LeaseLost):
        store.commit_chat(lease, profile_content(), "duplicate")
    assert counts(engine, sid)["profile_versions"] == 2
    assert counts(engine, sid)["messages"] == 2
    with engine.connect() as connection:
        roles = (
            connection.execute(
                text("SELECT role FROM messages WHERE task_id=:id ORDER BY role"),
                {"id": accepted.task_id},
            )
            .scalars()
            .all()
        )
    assert roles == ["assistant", "user"]


@pytest.mark.parametrize("expired", [False, True], ids=["revoked", "expired"])
def test_t16_session_invalidated_during_work_cannot_be_written_back(
    repo, sid, engine, clock, store, upload_dir, expired
):
    from app.platform.jobs.store import LeaseLost

    accepted = repo.document_create(
        sid,
        b"synthetic PDF bytes",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        upload_dir,
    )
    lease = store.claim()
    assert list(upload_dir.iterdir())
    if expired:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE sessions SET expires_at=:now WHERE id=:sid"),
                {"now": clock(), "sid": sid},
            )
    else:
        repo.revoke(sid)
    assert not store.heartbeat(lease)
    with pytest.raises(LeaseLost):
        store.commit_document(lease, profile_content())
    repo.cleanup_expired()
    repo.retry_file_cleanup(upload_dir)
    assert counts(engine, sid)["profiles"] == 0
    assert counts(engine, sid)["documents"] == 0
    assert counts(engine, sid)["tasks"] == 0
    assert list(upload_dir.iterdir()) == []
    assert accepted.task_id is not None


def finish_report(store, lease, work, item, index=0):
    from app.contracts.ports import TaskContext
    from app.platform.fakes import FakeReporting

    score = score_for(work, index)
    store.start_item(lease, item.id)
    store.save_score(lease, item.id, score)
    report = asyncio.run(
        FakeReporting().generate_report(
            work.profile,
            work.jobs[index],
            score,
            lease.model_snapshot,
            context=TaskContext(model_id=lease.model_id),
        )
    )
    return store.finish_item(lease, item.id, report=report, metadata=lease.model_snapshot)


@pytest.mark.parametrize("mode", ["succeeded", "mixed", "score_only", "failed"])
def test_t12_independent_item_commits_and_terminal_aggregation(repo, sid, engine, store, mode):
    accepted = prepared_diagnosis(repo, sid)
    lease = store.claim()
    work = store.load(lease)
    first, second = work.diagnosis.items
    if mode in {"succeeded", "mixed"}:
        saved_first = finish_report(store, lease, work, first)
        assert saved_first.status == "succeeded"
    elif mode == "score_only":
        store.start_item(lease, first.id)
        store.save_score(lease, first.id, score_for(work))
        saved_first = store.finish_item(lease, first.id, error=failure())
        assert saved_first.status == "score_only" and saved_first.score_result is not None
    else:
        saved_first = store.finish_item(lease, first.id, error=failure())
        assert saved_first.status == "failed" and saved_first.score_result is None
    # A finalized item cannot be rewritten while a different item is unfinished.
    assert store.finish_item(lease, first.id, error=failure("MODEL_TIMEOUT")) == saved_first
    assert store.start_item(lease, first.id) == saved_first
    assert store.save_score(lease, first.id, score_for(work)) == saved_first
    assert raw_task(engine, accepted.task_id)["status"] == "running"
    if mode == "succeeded":
        finish_report(store, lease, work, second, 1)
    else:
        store.finish_item(lease, second.id, error=failure())
    result = store.finish(lease)
    assert (
        result.status
        == {
            "succeeded": "succeeded",
            "mixed": "partial",
            "score_only": "partial",
            "failed": "failed",
        }[mode]
    )
    if mode == "failed":
        assert result.error is not None
    diagnosis = repo.owned(repo.diagnoses, accepted.diagnosis_id, sid).value
    assert diagnosis.items[0] == saved_first
    assert len(diagnosis.items) == 2
    with engine.connect() as connection:
        total = connection.scalar(
            text("SELECT count(*) FROM diagnosis_items WHERE diagnosis_id=:id"),
            {"id": accepted.diagnosis_id},
        )
    assert total == 2
    from app.platform.jobs.store import LeaseLost

    with pytest.raises(LeaseLost):
        store.finish_item(lease, second.id, error=failure())
    assert repo.owned(repo.diagnoses, accepted.diagnosis_id, sid).value == diagnosis


def test_t12_reclaim_preserves_score_and_deadline_preserves_completed_jobs(
    repo, sid, engine, clock, store
):
    from app.platform.jobs.store import LeaseLost

    accepted = prepared_diagnosis(repo, sid, number=3)
    first = store.claim()
    work = store.load(first)
    done, scored, pending = work.diagnosis.items
    done_result = finish_report(store, first, work, done)
    store.start_item(first, scored.id)
    score = score_for(work, 1)
    store.save_score(first, scored.id, score)
    clock.advance(61)
    second = store.claim()
    recovered = store.load(second)
    assert recovered.diagnosis.items[0] == done_result
    assert recovered.diagnosis.items[1].score_result == score
    assert second.attempt == 2
    with pytest.raises(LeaseLost):
        store.finish_item(first, scored.id, error=failure())
    # Preserve success and scoring even when the replacement cannot finish in time.
    clock.advance(240)
    store.reap()
    assert raw_task(engine, accepted.task_id)["status"] == "partial"
    diagnosis = repo.owned(repo.diagnoses, accepted.diagnosis_id, sid).value
    by_id = {item.id: item for item in diagnosis.items}
    assert by_id[done.id] == done_result
    assert by_id[scored.id].status == "score_only"
    assert by_id[scored.id].score_result == score
    assert by_id[scored.id].error.code == "TASK_TIMEOUT"
    assert by_id[pending.id].status == "failed"
    assert by_id[pending.id].score_result is None
    assert by_id[pending.id].error.code == "TASK_TIMEOUT"


def test_item_session_and_task_ownership_is_checked(repo, sid, store):
    from app.platform.jobs.store import LeaseLost

    accepted = prepared_diagnosis(repo, sid)
    other_sid = repo.create_session()[0].public.id
    other = prepared_diagnosis(repo, other_sid)
    first = store.claim()
    second = store.claim()
    assert {first.task_id, second.task_id} == {accepted.task_id, other.task_id}
    foreign_item = store.load(second).diagnosis.items[0]
    with pytest.raises((LeaseLost, PlatformError)):
        store.finish_item(first, foreign_item.id, error=failure())
    assert store.load(second).diagnosis.items[0].status == "pending"


def test_document_success_releases_original_and_has_one_profile(
    repo, sid, engine, store, upload_dir
):
    from app.platform.jobs.store import LeaseLost

    accepted = repo.document_create(
        sid,
        b"synthetic PDF bytes",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        upload_dir,
    )
    lease = store.claim()
    saved = store.commit_document(lease, profile_content("parsed synthetic document"))
    assert saved.version == 1
    with pytest.raises(LeaseLost):
        store.commit_document(lease, profile_content())
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT status FROM documents WHERE session_id=:sid"), {"sid": sid}
            )
            == "parsed"
        )
    repo.retry_file_cleanup(upload_dir)
    assert counts(engine, sid)["profiles"] == 1
    assert counts(engine, sid)["profile_versions"] == 1
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("SELECT status, storage_key, profile_id FROM documents WHERE session_id=:sid"),
                {"sid": sid},
            )
            .mappings()
            .one()
        )
    assert row["status"] == "deleted" and row["storage_key"] is None
    assert str(row["profile_id"]) == saved.id
    assert raw_task(engine, accepted.task_id)["status"] == "succeeded"
    assert list(upload_dir.iterdir()) == []


def worker_for(repo, upload_dir, **ports):
    from app.platform.jobs.worker import create_worker
    from app.settings import Settings

    return create_worker(Settings(_env_file=None, upload_dir=upload_dir), repository=repo, **ports)


def enqueue_worker_job(repo, sid, worker):
    from app.contracts import JobCreate
    from app.intake import SYNTHETIC_JOB_RAW_TEXT
    from app.platform.database_service import DatabasePlatform

    platform = DatabasePlatform(repo, worker.catalog, worker.upload_dir)
    return platform.job_create(
        sid,
        JobCreate(raw_text=SYNTHETIC_JOB_RAW_TEXT, company_context="", model_id="demo-model-a"),
        uuid4().hex,
    )


def test_model_wait_renews_lease_and_holds_no_database_transaction(
    repo, sid, engine, clock, upload_dir
):
    from app.intake import SyntheticIntake

    class PausedIntake(SyntheticIntake):
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def extract_job(self, *args, **kwargs):
            self.entered.set()
            await self.release.wait()
            return await super().extract_job(*args, **kwargs)

    async def run():
        intake = PausedIntake()
        worker = worker_for(repo, upload_dir, intake=intake, heartbeat_seconds=0.01)
        accepted = enqueue_worker_job(repo, sid, worker)
        running = asyncio.create_task(worker.run_once())
        try:
            await asyncio.wait_for(intake.entered.wait(), 5)
            before = raw_task(engine, accepted.task_id)
            clock.advance(15)
            for _ in range(100):
                current = await asyncio.to_thread(raw_task, engine, accepted.task_id)
                if current["heartbeat_at"] == clock():
                    break
                await asyncio.sleep(0.01)
            assert current["heartbeat_at"] == clock()
            assert current["lease_until"] > before["lease_until"]
            assert current["status"] == "running" and current["attempt"] == 1
            # Read-only observation of actual server sessions, not a mock counter.
            with engine.connect() as connection:
                app = connection.scalar(text("SHOW application_name"))
                held = connection.scalar(
                    text("""SELECT count(*) FROM pg_stat_activity
                            WHERE application_name=:app AND pid<>pg_backend_pid()
                              AND state LIKE 'idle in transaction%'"""),
                    {"app": app},
                )
            assert held == 0, "Model/network waiting must not retain a SQL transaction"
        finally:
            intake.release.set()
            await asyncio.wait_for(running, 5)
        assert raw_task(engine, accepted.task_id)["status"] == "succeeded"
        assert counts(engine, sid)["job_versions"] == 1

    asyncio.run(run())


def test_t16_worker_revoke_at_port_sync_point_discards_late_result(repo, sid, engine, upload_dir):
    from app.intake import SyntheticIntake

    class PausedIntake(SyntheticIntake):
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def extract_job(self, *args, **kwargs):
            self.entered.set()
            await self.release.wait()
            return await super().extract_job(*args, **kwargs)

    async def run():
        intake = PausedIntake()
        worker = worker_for(repo, upload_dir, intake=intake)
        enqueue_worker_job(repo, sid, worker)
        running = asyncio.create_task(worker.run_once())
        try:
            await asyncio.wait_for(intake.entered.wait(), 5)
            await asyncio.to_thread(repo.revoke, sid)
        finally:
            intake.release.set()
            await asyncio.wait_for(running, 5)
        assert counts(engine, sid)["jobs"] == 0
        assert counts(engine, sid)["job_versions"] == 0
        assert counts(engine, sid)["tasks"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("changed", [False, True], ids=["disabled", "mapping-changed"])
def test_worker_refuses_disabled_or_reconfigured_model(repo, sid, engine, upload_dir, changed):
    from dataclasses import replace

    worker = worker_for(repo, upload_dir)
    accepted = enqueue_worker_job(repo, sid, worker)
    directory = worker.catalog.directory
    if changed:
        directory.entries = tuple(
            replace(entry, model="different-synthetic-model") for entry in directory.entries
        )
    else:
        directory.disable("demo-model-a")
    assert asyncio.run(worker.run_once())
    row = raw_task(engine, accepted.task_id)
    assert row["status"] == "failed" and row["error"]["code"] == "MODEL_UNAVAILABLE"
    assert counts(engine, sid)["jobs"] == 0


def test_worker_recovery_skips_persisted_score_and_terminal_item(
    repo, sid, engine, clock, upload_dir, store
):
    from app.contracts import DiagnosisCreate
    from app.platform.database_service import DatabasePlatform
    from app.scoring import ScoringService

    class NoRecompute(ScoringService):
        def assess_requirements(self, *args, **kwargs):
            pytest.fail("Recovery must reuse persisted scoring")

    worker = worker_for(repo, upload_dir, scoring=NoRecompute())
    platform = DatabasePlatform(repo, worker.catalog, upload_dir)
    p = profile(repo, sid)
    repo.confirm(repo.profiles, p.id, sid, p.version)
    js = [job(repo, sid) for _ in range(2)]
    for j in js:
        repo.confirm(repo.jobs, j.id, sid, j.version)
    accepted = platform.diagnosis_create(
        sid,
        DiagnosisCreate.model_validate(diagnosis_body(p, *js).model_dump()),
        uuid4().hex,
    )
    first = store.claim()
    work = store.load(first)
    done = finish_report(store, first, work, work.diagnosis.items[0])
    store.save_score(first, work.diagnosis.items[1].id, score_for(work, 1))
    clock.advance(61)
    assert asyncio.run(worker.run_once())
    assert raw_task(engine, accepted.task_id)["status"] == "succeeded"
    diagnosis = repo.owned(repo.diagnoses, accepted.diagnosis_id, sid).value
    assert diagnosis.items[0] == done
    assert all(item.status == "succeeded" for item in diagnosis.items)


def test_deadline_cancels_model_even_while_heartbeat_waits_on_pg_lock(
    repo, sid, engine, upload_dir
):
    from app.intake import SyntheticIntake

    class NeverFinishes(SyntheticIntake):
        def __init__(self):
            self.entered = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def extract_job(self, *args, **kwargs):
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()

    async def run():
        intake = NeverFinishes()
        worker = worker_for(repo, upload_dir, intake=intake, heartbeat_seconds=0.01)
        accepted = enqueue_worker_job(repo, sid, worker)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE tasks SET deadline_at=:deadline WHERE id=:id"),
                {"deadline": repo.clock() + timedelta(seconds=0.5), "id": accepted.task_id},
            )
        running = asyncio.create_task(worker.run_once())
        blocker = engine.connect()
        transaction = blocker.begin()
        try:
            await asyncio.wait_for(intake.entered.wait(), 5)
            blocker.execute(
                text("SELECT id FROM tasks WHERE id=:id FOR UPDATE"),
                {"id": accepted.task_id},
            )
            app = blocker.scalar(text("SHOW application_name"))
            blocked = 0
            for _ in range(100):
                with engine.connect() as observer:
                    blocked = observer.scalar(
                        text("""SELECT count(*) FROM pg_stat_activity
                                WHERE application_name=:app AND pid<>pg_backend_pid()
                                  AND wait_event_type='Lock' AND state='active'"""),
                        {"app": app},
                    )
                if blocked:
                    break
                await asyncio.sleep(0.005)
            assert blocked, "The heartbeat must actually wait on a PostgreSQL task lock"
            # The task row remains locked here: a heartbeat-driven timer would hang.
            await asyncio.wait_for(intake.cancelled.wait(), 3)
            assert transaction.is_active
        finally:
            transaction.commit()
            blocker.close()
            await asyncio.wait_for(running, 5)
        await asyncio.to_thread(worker.store.reap)
        row = raw_task(engine, accepted.task_id)
        assert row["status"] == "failed" and row["error"]["code"] == "TASK_TIMEOUT"
        assert counts(engine, sid)["jobs"] == 0

    asyncio.run(run())


def test_commit_rechecks_lease_after_waiting_on_profile_lock(repo, sid, engine, clock, store):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.platform.jobs.store import LeaseLost

    p = profile(repo, sid)
    repo.create_task(
        sid,
        "profile_chat",
        "demo-model-a",
        snapshot(repo),
        {"profile": {"id": p.id, "version": 1}, "base_version": 1, "content": "Python"},
        uuid4().hex,
        f"chat:{p.id}",
        {"content": "Python", "base_version": 1, "model_id": "demo-model-a"},
        profile_id=p.id,
    )
    lease = store.claim()
    with engine.begin() as blocker:
        blocker.execute(text("SELECT id FROM profiles WHERE id=:id FOR UPDATE"), {"id": p.id})
        app = blocker.scalar(text("SHOW application_name"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                store.commit_chat, lease, profile_content("must roll back"), "No stale message"
            )
            try:
                until = time.monotonic() + 5
                blocked = 0
                while time.monotonic() < until:
                    with engine.connect() as observer:
                        blocked = observer.scalar(
                            text("""SELECT count(*) FROM pg_stat_activity
                                    WHERE application_name=:app AND pid<>pg_backend_pid()
                                      AND wait_event_type='Lock' AND state='active'"""),
                            {"app": app},
                        )
                    if blocked:
                        break
                    time.sleep(0.01)
                assert blocked, "Commit must actually wait on a PostgreSQL profile lock"
                clock.advance(61)
            finally:
                blocker.commit()
            with pytest.raises(LeaseLost):
                pending.result(timeout=5)
    assert counts(engine, sid)["profile_versions"] == 1
    assert counts(engine, sid)["messages"] == 0
    assert repo.version(repo.profiles, p.id, sid) == p


def test_legacy_unfenced_task_write_paths_are_rejected(repo, sid, engine):
    from app.platform.jobs.store import LeaseLost

    p = profile(repo, sid)
    accepted = task(repo, sid)
    before = counts(engine, sid)
    with pytest.raises(LeaseLost):
        repo.create_job(sid, "Python", job_content(), created_by_task_id=accepted.task_id)
    with pytest.raises(LeaseLost):
        repo.append(
            repo.profiles,
            p.id,
            sid,
            1,
            content=profile_content("unfenced"),
            created_by_task_id=accepted.task_id,
        )
    with pytest.raises(LeaseLost):
        repo.commit_profile_task(
            sid, accepted.task_id, p.id, 1, profile_content("unfenced"), "user", "assistant"
        )
    assert counts(engine, sid) == before
    assert raw_task(engine, accepted.task_id)["status"] == "queued"


@pytest.mark.parametrize("all_scoring_fail", [False, True], ids=["score-only", "all-failed"])
def test_worker_real_score_report_failure_aggregation(
    repo, sid, engine, upload_dir, all_scoring_fail
):
    from app.contracts import DiagnosisCreate
    from app.llm import FakeModelDirectory, FakeModelGateway
    from app.platform.database_service import DatabasePlatform
    from app.scoring import ScoringService

    class FailingScore(ScoringService):
        def assess_requirements(self, *args, **kwargs):
            raise PlatformError(422, "MODEL_OUTPUT_INVALID", "Synthetic scoring failure")

    gateway = FakeModelGateway(FakeModelDirectory(), failures={"diagnosis_report": "invalid_json"})
    worker = worker_for(
        repo,
        upload_dir,
        gateway=gateway,
        **({"scoring": FailingScore()} if all_scoring_fail else {}),
    )
    platform = DatabasePlatform(repo, worker.catalog, upload_dir)
    p = profile(repo, sid)
    repo.confirm(repo.profiles, p.id, sid, p.version)
    jobs = [job(repo, sid) for _ in range(2)]
    for j in jobs:
        repo.confirm(repo.jobs, j.id, sid, j.version)
    accepted = platform.diagnosis_create(
        sid, DiagnosisCreate.model_validate(diagnosis_body(p, *jobs).model_dump()), uuid4().hex
    )
    assert asyncio.run(worker.run_once())
    row = raw_task(engine, accepted.task_id)
    diagnosis = repo.owned(repo.diagnoses, accepted.diagnosis_id, sid).value
    assert row["status"] == ("failed" if all_scoring_fail else "partial")
    assert all(
        item.status == ("failed" if all_scoring_fail else "score_only") for item in diagnosis.items
    )
    assert all((item.score_result is None) == all_scoring_fail for item in diagnosis.items)
    assert all(item.report is None and item.error is not None for item in diagnosis.items)
    if all_scoring_fail:
        assert gateway.calls == []
    else:
        # Gateway owns its one shared retry; worker does not loop over the call.
        assert len(gateway.calls) == 2
        assert all(call.attempts == 2 for call in gateway.calls)
    assert raw_task(engine, accepted.task_id)["attempt"] == 1


def test_cancelled_document_read_closes_handle_when_io_thread_returns(
    repo, sid, engine, upload_dir, monkeypatch
):
    from threading import Event

    from app.platform.database_service import DatabasePlatform
    from app.platform.jobs import worker as worker_module

    entered, release, closed = Event(), Event(), Event()
    handles = []
    original_fdopen = os.fdopen

    class DelayedRead:
        def __init__(self, handle):
            self.handle = handle
            handles.append(handle)

        def __enter__(self):
            return self

        def read(self, limit):
            entered.set()
            assert release.wait(5), "Parent must release the I/O thread after cancellation"
            return self.handle.read(limit)

        def __exit__(self, *_):
            self.handle.close()
            closed.set()

    async def run():
        worker = worker_for(repo, upload_dir, heartbeat_seconds=0.01)
        platform = DatabasePlatform(repo, worker.catalog, upload_dir)
        accepted = platform.document(
            sid, b"synthetic bytes", "application/pdf", "demo-model-a", uuid4().hex
        )
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE tasks SET deadline_at=:deadline WHERE id=:id"),
                {"deadline": repo.clock() + timedelta(seconds=0.3), "id": accepted.task_id},
            )
        monkeypatch.setattr(
            worker_module.os, "fdopen", lambda *a, **kw: DelayedRead(original_fdopen(*a, **kw))
        )
        running = asyncio.create_task(worker.run_once())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            # Cancellation must not wait for the blocking read to return.
            assert await asyncio.wait_for(running, 3)
            assert not release.is_set()
            assert raw_task(engine, accepted.task_id)["status"] == "failed"
        finally:
            release.set()
            assert await asyncio.to_thread(closed.wait, 3)
            await asyncio.wait_for(running, 5)
        assert len(handles) == 1 and handles[0].closed
        assert counts(engine, sid)["profiles"] == 0
        repo.retry_file_cleanup(upload_dir)
        assert list(upload_dir.iterdir()) == []

    asyncio.run(run())
