"""DB-01 acceptance against a migrated, disposable PostgreSQL database.

Set RD_TEST_DATABASE_URL to the dedicated database created by the documented
DB-01 procedure. The fixture never creates, drops or truncates a database.
All inputs are synthetic; no provider or worker is invoked here.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest

sa = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.contracts import DiagnosisCreate, JobContent, ProfileContent, ProfileCreate  # noqa: E402
from app.platform.errors import PlatformError  # noqa: E402


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("RD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("RD_TEST_DATABASE_URL is required for PostgreSQL acceptance")
    parsed = sa.engine.make_url(url)
    assert parsed.get_backend_name() == "postgresql", "PostgreSQL is required; no SQLite substitute"
    assert parsed.database and "test" in parsed.database.lower(), "Use a dedicated test database"
    database = create_engine(
        url,
        pool_size=8,
        connect_args={"application_name": f"rd-db01-tests-{uuid4().hex}"},
    )
    with database.connect() as connection:
        assert connection.scalar(text("SELECT version()")).startswith("PostgreSQL")
        assert connection.scalar(text("SELECT version_num FROM alembic_version"))
    yield database
    database.dispose()


@pytest.fixture(scope="module")
def upload_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("db01-uploads")


@pytest.fixture
def repo(engine, upload_dir):
    from app.platform.repositories import PostgreSQLRepository

    repository = PostgreSQLRepository(engine)
    sessions = []
    original = repository.create_session

    def create_session(*args, **kwargs):
        record, token = original(*args, **kwargs)
        sessions.append(record.public.id)
        return record, token

    repository.create_session = create_session
    yield repository
    for sid in sessions:
        repository.revoke(sid)
    repository.retry_file_cleanup(upload_dir)


@pytest.fixture
def sid(repo):
    return repo.create_session()[0].public.id


def profile_content(overview="synthetic profile"):
    return ProfileContent(
        overview=overview,
        as_of_month="2026-09",
        facts=[],
        evidence=[],
    )


def profile(repo, sid, *, key=None):
    return repo.profile_create(sid, ProfileCreate(content=profile_content()), key or uuid4().hex)


def job_content(*, ignored=False):
    return JobContent.model_validate(
        {
            "title": "Synthetic Python engineer",
            "company_name": None,
            "company_context": "",
            "requirements": [
                {
                    "id": "r1",
                    "quote": "Python",
                    "category": "skill",
                    "importance": "must",
                    "operator": "has_skill",
                    "target": "Python",
                    "subject": None,
                    "ignored": ignored,
                    "ignore_reason": "synthetic irrelevant requirement" if ignored else None,
                }
            ],
        }
    )


def job(repo, sid, *, ignored=False):
    return repo.create_job(sid, "Python", job_content(ignored=ignored))


def snapshot(repo):
    return {
        "model_id": "demo-model-a",
        "provider": "fake",
        "model": "db01-synthetic",
        "gateway_config_version": "db01-v1",
        "prompt_version": "db01-v1",
        "generated_at": repo.now(),
    }


def task(repo, sid, *, key=None, body=None, operation="job_create"):
    return repo.create_task(
        sid,
        "job_parse",
        "demo-model-a",
        snapshot(repo),
        {"raw_text": "Python", "company_context": ""},
        key or uuid4().hex,
        operation,
        body or {"raw_text": "Python", "company_context": "", "model_id": "demo-model-a"},
    )


def diagnosis_body(p, *jobs):
    return DiagnosisCreate.model_validate(
        {
            "profile": {"id": p.id, "version": p.version},
            "jobs": [{"id": j.id, "version": j.version} for j in jobs],
            "model_id": "demo-model-a",
        }
    )


def counts(engine, sid):
    with engine.connect() as connection:
        return {
            table: connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE session_id = :sid"), {"sid": sid}
            )
            for table in (
                "profiles",
                "profile_versions",
                "jobs",
                "job_versions",
                "tasks",
                "diagnoses",
                "diagnosis_items",
                "idempotency_keys",
                "messages",
                "documents",
            )
        }


def expect_error(status, code, action):
    with pytest.raises(PlatformError) as caught:
        action()
    assert caught.value.status == status
    assert caught.value.info.code == code


def race(actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        barrier.wait(timeout=10)
        try:
            return action()
        except PlatformError as error:
            return error

    with ThreadPoolExecutor(max_workers=len(actions)) as workers:
        return list(workers.map(invoke, actions))


def test_t04_concurrent_edits_wait_for_database_row_lock(repo, sid, engine):
    p = profile(repo, sid)
    barrier = Barrier(3)

    def edit(label):
        barrier.wait(timeout=10)
        try:
            return repo.append(repo.profiles, p.id, sid, 1, content=profile_content(label))
        except PlatformError as error:
            return error

    with engine.begin() as blocker:
        blocker.execute(text("SELECT id FROM profiles WHERE id=:id FOR UPDATE"), {"id": p.id})
        app_name = blocker.scalar(text("SHOW application_name"))
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(edit, label) for label in ("first edit", "second edit")]
            barrier.wait(timeout=10)
            try:
                deadline = time.monotonic() + 10
                blocked = 0
                while time.monotonic() < deadline:
                    with engine.connect() as observer:
                        blocked = observer.scalar(
                            text("""SELECT count(*) FROM pg_stat_activity
                                    WHERE application_name=:app AND state='active'
                                      AND wait_event_type='Lock' AND pid <> pg_backend_pid()"""),
                            {"app": app_name},
                        )
                    if blocked >= 2:
                        break
                    time.sleep(0.02)
                assert blocked >= 2, "Both edits must demonstrably wait on PostgreSQL locks"
            finally:
                # Release the held parent row before waiting for the pool's threads.
                blocker.commit()
            outcomes = [future.result(timeout=10) for future in futures]
    successes = [value for value in outcomes if not isinstance(value, PlatformError)]
    errors = [value for value in outcomes if isinstance(value, PlatformError)]
    assert len(successes) == len(errors) == 1
    assert (errors[0].status, errors[0].info.code) == (409, "VERSION_CONFLICT")
    latest = repo.version(repo.profiles, p.id, sid)
    assert latest == successes[0] and latest.version == 2
    assert repo.version(repo.profiles, p.id, sid, 1) == p
    assert counts(engine, sid)["profile_versions"] == 2
    # A delayed background result carries the same stale base and cannot overwrite the edit.
    expect_error(
        409,
        "VERSION_CONFLICT",
        lambda: repo.append(
            repo.profiles, p.id, sid, 1, content=profile_content("stale background extraction")
        ),
    )
    assert repo.version(repo.profiles, p.id, sid) == latest


def test_t13_concurrent_profile_key_and_original_snapshot(repo, sid, engine):
    key = uuid4().hex
    results = race([lambda: profile(repo, sid, key=key)] * 2)
    assert results[0] == results[1] and not isinstance(results[0], PlatformError)
    first = results[0]
    assert counts(engine, sid)["profiles"] == 1
    assert counts(engine, sid)["idempotency_keys"] == 1
    repo.append(repo.profiles, first.id, sid, 1, content=profile_content("edited later"))
    assert profile(repo, sid, key=key) == first
    expect_error(
        409,
        "IDEMPOTENCY_CONFLICT",
        lambda: repo.profile_create(
            sid, ProfileCreate(content=profile_content("different body")), key
        ),
    )
    expect_error(409, "IDEMPOTENCY_CONFLICT", lambda: task(repo, sid, key=key))
    assert counts(engine, sid)["tasks"] == 0


def test_t13_concurrent_task_replay_enqueues_once_and_normalizes_json(repo, sid, engine):
    key = uuid4().hex
    body = {"raw_text": "Python", "company_context": "", "model_id": "demo-model-a"}
    reordered = dict(reversed(list(body.items())))
    results = race(
        [
            lambda: task(repo, sid, key=key, body=body),
            lambda: task(repo, sid, key=key, body=reordered),
        ]
    )
    assert results[0] == results[1] and not isinstance(results[0], PlatformError)
    assert counts(engine, sid)["tasks"] == 1
    assert counts(engine, sid)["idempotency_keys"] == 1
    assert repo.owned(repo.tasks, results[0].task_id, sid).value.status == "queued"
    expect_error(
        409,
        "IDEMPOTENCY_CONFLICT",
        lambda: task(repo, sid, key=key, body={**body, "raw_text": "SQL"}),
    )
    expect_error(
        409,
        "IDEMPOTENCY_CONFLICT",
        lambda: repo.replay(sid, key, "document", body),
    )
    assert counts(engine, sid)["tasks"] == 1


def test_latest_confirmation_and_frozen_historical_diagnosis(repo, sid, engine):
    from app.platform.repositories.schema import diagnosis_items, tasks

    p, j = profile(repo, sid), job(repo, sid)
    p = repo.confirm(repo.profiles, p.id, sid, 1)
    j = repo.confirm(repo.jobs, j.id, sid, 1)
    assert repo.confirm(repo.profiles, p.id, sid, 1) == p
    first = repo.diagnosis_create(sid, diagnosis_body(p, j), uuid4().hex, snapshot(repo))
    # Seed a completed synthetic report; worker execution/leases belong to JOB-01.
    score = {
        "score": 0,
        "unknown_weight_ratio": 1,
        "rule_version": "synthetic-v1",
        "matcher_version": "synthetic-v1",
        "assessments": [
            {
                "requirement_id": "r1",
                "category": "skill",
                "importance": "must",
                "status": "unknown",
                "weight": 2,
                "coefficient": 0,
                "evidence_ids": [],
                "reason": "Synthetic profile has no evidence",
            }
        ],
        "dimensions": [{"category": "skill", "score": 0}],
    }
    report = {"summary": "Frozen synthetic report", "gaps": [], "suggestions": [], "actions": []}
    with engine.begin() as connection:
        connection.execute(
            diagnosis_items.update()
            .where(diagnosis_items.c.diagnosis_id == first.diagnosis_id)
            .values(
                status="succeeded", score_result=score, report=report, model_metadata=snapshot(repo)
            )
        )
        connection.execute(
            tasks.update()
            .where(tasks.c.id == first.task_id)
            .values(
                status="succeeded",
                result={
                    "resource_type": "diagnosis",
                    "resource_id": first.diagnosis_id,
                    "version": None,
                    "assistant_message": None,
                },
            )
        )
    frozen = repo.owned(repo.diagnoses, first.diagnosis_id, sid).value
    assert frozen.items[0].report.summary == "Frozen synthetic report"
    p2 = repo.append(repo.profiles, p.id, sid, 1, content=profile_content("later edit"))
    repo.append(repo.jobs, j.id, sid, 1, raw_text="new Python JD", content=job_content())
    assert not p2.confirmed
    expect_error(409, "VERSION_CONFLICT", lambda: repo.confirm(repo.profiles, p.id, sid, 1))
    assert repo.version(repo.profiles, p.id, sid, 1) == p
    assert repo.version(repo.jobs, j.id, sid, 1) == j
    assert repo.owned(repo.diagnoses, first.diagnosis_id, sid).value == frozen
    # Historical confirmed versions remain legal for a new diagnosis.
    second = repo.diagnosis_create(sid, diagnosis_body(p, j), uuid4().hex, snapshot(repo))
    assert second.diagnosis_id != first.diagnosis_id
    stored = repo.owned(repo.diagnoses, second.diagnosis_id, sid).value
    assert stored.profile.version == stored.items[0].job.version == 1
    assert counts(engine, sid)["diagnosis_items"] == 2


@pytest.mark.parametrize("invalid", ["unconfirmed", "unscorable", "foreign", "duplicate"])
def test_diagnosis_validation_rolls_back_every_insert(repo, sid, engine, invalid):
    p, good = profile(repo, sid), job(repo, sid)
    p = repo.confirm(repo.profiles, p.id, sid, 1)
    good = repo.confirm(repo.jobs, good.id, sid, 1)
    bad_sid = repo.create_session()[0].public.id if invalid == "foreign" else sid
    bad = job(repo, bad_sid, ignored=invalid == "unscorable")
    if invalid != "unconfirmed":
        bad = repo.confirm(repo.jobs, bad.id, bad_sid, 1)
    jobs = [good, bad]
    if invalid == "duplicate":
        other = repo.append(repo.jobs, good.id, sid, 1, raw_text="Python", content=job_content())
        other = repo.confirm(repo.jobs, good.id, sid, other.version)
        jobs = [good, other]
    body = diagnosis_body(p, *jobs)
    before = counts(engine, sid)
    expected = {
        "unconfirmed": (422, "UNCONFIRMED_VERSION"),
        "unscorable": (422, "NO_SCORABLE_REQUIREMENTS"),
        "foreign": (404, "RESOURCE_NOT_FOUND"),
        "duplicate": (422, "VALIDATION_ERROR"),
    }[invalid]
    expect_error(*expected, lambda: repo.diagnosis_create(sid, body, uuid4().hex, snapshot(repo)))
    assert counts(engine, sid) == before


def test_t15_cross_session_reads_edits_confirmation_and_diagnoses_are_hidden(repo, sid):
    other = repo.create_session()[0].public.id
    p, j = profile(repo, sid), job(repo, sid)
    p = repo.confirm(repo.profiles, p.id, sid, 1)
    j = repo.confirm(repo.jobs, j.id, sid, 1)
    accepted = repo.diagnosis_create(sid, diagnosis_body(p, j), uuid4().hex, snapshot(repo))
    for table, resource in ((repo.profiles, p), (repo.jobs, j)):
        for version in (None, 1):
            expect_error(
                404, "RESOURCE_NOT_FOUND", lambda: repo.version(table, resource.id, other, version)
            )
        expect_error(404, "RESOURCE_NOT_FOUND", lambda: repo.confirm(table, resource.id, other, 1))
        expect_error(
            404,
            "RESOURCE_NOT_FOUND",
            lambda: repo.append(table, resource.id, other, 1, content=resource.content),
        )
    for table, rid in ((repo.tasks, accepted.task_id), (repo.diagnoses, accepted.diagnosis_id)):
        expect_error(404, "RESOURCE_NOT_FOUND", lambda: repo.owned(table, rid, other))
    expect_error(
        404,
        "RESOURCE_NOT_FOUND",
        lambda: repo.diagnosis_create(other, diagnosis_body(p, j), uuid4().hex, snapshot(repo)),
    )


def test_database_rejects_cross_session_versions_and_content_mutation(repo, sid, engine):
    p, j = profile(repo, sid), job(repo, sid)
    other = repo.create_session()[0].public.id
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO profile_versions
                    (profile_id,session_id,version,content,created_at)
                    VALUES (:id,:sid,2,CAST(:content AS jsonb),now())"""),
            {"id": p.id, "sid": other, "content": p.content.model_dump_json()},
        )
    for table, column, resource, payload in (
        ("profile_versions", "profile_id", p, profile_content("illegal rewrite")),
        ("job_versions", "job_id", j, job_content(ignored=True)),
    ):
        with pytest.raises(sa.exc.DBAPIError), engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {table} SET content=CAST(:body AS jsonb) WHERE {column}=:id"),
                {"body": payload.model_dump_json(), "id": resource.id},
            )
    assert repo.version(repo.profiles, p.id, sid, 1) == p
    assert repo.version(repo.jobs, j.id, sid, 1) == j


def test_fixed_session_expiry_revocation_and_cleanup(repo, engine):
    current = [datetime(2026, 10, 1, tzinfo=UTC)]
    repo.clock = lambda: current[0]
    record, token = repo.create_session()
    sid = record.public.id
    p = profile(repo, sid)
    assert record.expires_at == current[0] + timedelta(days=7)
    current[0] += timedelta(days=6)
    assert repo.authenticate(token).public == record.public
    assert repo.version(repo.profiles, p.id, sid) == p
    assert repo.active(sid).expires_at == record.expires_at
    current[0] += timedelta(days=1)
    expect_error(401, "SESSION_EXPIRED", lambda: repo.authenticate(token))
    expect_error(401, "SESSION_EXPIRED", lambda: repo.version(repo.profiles, p.id, sid))
    repo.cleanup_expired()
    assert all(count == 0 for count in counts(engine, sid).values())
    fresh, token = repo.create_session()
    profile(repo, fresh.public.id)
    repo.revoke(fresh.public.id)
    expect_error(401, "SESSION_EXPIRED", lambda: repo.authenticate(token))
    assert all(count == 0 for count in counts(engine, fresh.public.id).values())


def test_t04_background_commit_refuses_stale_base_without_messages(repo, sid, engine):
    from app.platform.jobs.store import JobStore

    p = profile(repo, sid)
    accepted = repo.create_task(
        sid,
        "profile_chat",
        "demo-model-a",
        snapshot(repo),
        {
            "profile": {"id": p.id, "version": 1},
            "base_version": 1,
            "content": "synthetic user message",
        },
        uuid4().hex,
        f"chat:{p.id}",
        {"base_version": 1, "content": "synthetic user message", "model_id": "demo-model-a"},
        profile_id=p.id,
    )
    lease = JobStore(repo).claim()
    assert lease.task_id == accepted.task_id
    latest = repo.append(repo.profiles, p.id, sid, 1, content=profile_content("manual correction"))
    expect_error(
        409,
        "VERSION_CONFLICT",
        lambda: repo.commit_profile_task(
            sid,
            accepted.task_id,
            p.id,
            1,
            profile_content("stale model result"),
            "synthetic user message",
            "synthetic assistant message",
            lease_token=lease.token,
        ),
    )
    assert repo.version(repo.profiles, p.id, sid) == latest
    assert repo.owned(repo.profiles, p.id, sid).messages == []
    assert counts(engine, sid)["messages"] == 0
    assert counts(engine, sid)["profile_versions"] == 2


def test_t15_successful_message_commit_is_atomic_and_session_scoped(repo, sid, engine):
    from app.platform.jobs.store import JobStore

    p = profile(repo, sid)
    accepted = repo.create_task(
        sid,
        "profile_chat",
        "demo-model-a",
        snapshot(repo),
        {
            "profile": {"id": p.id, "version": 1},
            "base_version": 1,
            "content": "synthetic user message",
        },
        uuid4().hex,
        f"chat:{p.id}",
        {"base_version": 1, "content": "synthetic user message", "model_id": "demo-model-a"},
        profile_id=p.id,
    )
    lease = JobStore(repo).claim()
    assert lease.task_id == accepted.task_id
    other = repo.create_session()[0].public.id
    expect_error(
        404,
        "RESOURCE_NOT_FOUND",
        lambda: repo.commit_profile_task(
            other,
            accepted.task_id,
            p.id,
            1,
            profile_content("foreign content"),
            "foreign user",
            "foreign assistant",
            lease_token=lease.token,
        ),
    )
    assert counts(engine, sid)["messages"] == 0
    updated = repo.commit_profile_task(
        sid,
        accepted.task_id,
        p.id,
        1,
        profile_content("successful conversation"),
        "synthetic user message",
        "synthetic assistant message",
        lease_token=lease.token,
    )
    assert updated.version == 2
    messages = repo.owned(repo.profiles, p.id, sid).messages
    assert [(m.role, m.content) for m in messages] == [
        ("user", "synthetic user message"),
        ("assistant", "synthetic assistant message"),
    ]
    expect_error(404, "RESOURCE_NOT_FOUND", lambda: repo.owned(repo.profiles, p.id, other))
    assert counts(engine, sid)["messages"] == 2
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("""SELECT count(*) FROM messages m
            JOIN tasks t ON t.id=m.task_id JOIN profiles p ON p.id=m.profile_id
            WHERE m.session_id=:sid AND (m.session_id<>t.session_id OR m.session_id<>p.session_id)
            """),
                {"sid": sid},
            )
            == 0
        )


def test_upload_replay_hashes_file_bytes_and_model_and_keeps_one_file(
    repo, sid, engine, upload_dir
):
    data = b"%PDF-1.4\nsynthetic document\n%%EOF\n"
    key = uuid4().hex
    accepted = repo.document_create(
        sid, data, "application/pdf", "demo-model-a", key, snapshot(repo), upload_dir
    )
    files = sorted(path.name for path in upload_dir.iterdir())
    assert len(files) == 1
    assert (
        repo.document_create(
            sid, data, "application/pdf", "demo-model-a", key, snapshot(repo), upload_dir
        )
        == accepted
    )
    expect_error(
        409,
        "IDEMPOTENCY_CONFLICT",
        lambda: repo.document_create(
            sid,
            data + b"changed",
            "application/pdf",
            "demo-model-a",
            key,
            snapshot(repo),
            upload_dir,
        ),
    )
    model_b = {**snapshot(repo), "model_id": "demo-model-b"}
    expect_error(
        409,
        "IDEMPOTENCY_CONFLICT",
        lambda: repo.document_create(
            sid, data, "application/pdf", "demo-model-b", key, model_b, upload_dir
        ),
    )
    assert sorted(path.name for path in upload_dir.iterdir()) == files
    assert counts(engine, sid)["documents"] == counts(engine, sid)["tasks"] == 1


def test_revocation_queues_file_deletion_and_failed_unlink_is_retried(
    repo, sid, engine, upload_dir
):
    repo.document_create(
        sid,
        b"%PDF-1.4\nsynthetic document\n%%EOF\n",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        upload_dir,
    )
    with engine.connect() as connection:
        storage_key = connection.scalar(
            text("SELECT storage_key FROM documents WHERE session_id=:sid"), {"sid": sid}
        )
    file = upload_dir / storage_key
    storage_key = file.name
    file.unlink()
    file.mkdir()  # Deliberate OS unlink failure, without permission-dependent behavior.
    repo.revoke(sid)
    assert all(count == 0 for count in counts(engine, sid).values())
    repo.retry_file_cleanup(upload_dir)
    with engine.connect() as connection:
        queue = (
            connection.execute(
                text("SELECT * FROM file_cleanup WHERE storage_key=:key"), {"key": storage_key}
            )
            .mappings()
            .one()
        )
        assert queue["attempt"] >= 1
        assert queue["next_attempt_at"] is not None
        assert "original_name" not in queue and "session_id" not in queue
    file.rmdir()
    file.write_bytes(b"synthetic temporary bytes")
    repo.clock = lambda: datetime.now(UTC) + timedelta(days=2)
    assert repo.retry_file_cleanup(upload_dir) >= 1
    assert not file.exists()
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM file_cleanup WHERE storage_key=:key"),
                {"key": storage_key},
            )
            == 0
        )


def test_database_http_status_replay_isolation_and_revocation(repo, sid, engine):
    import asyncio

    import httpx

    from app.database import create_app
    from app.platform.catalog import FakeModelCatalog
    from app.settings import Settings
    from app.tools.check_contracts import compare_routes, load_design

    async def run():
        app = create_app(Settings(_env_file=None), repository=repo, catalog=FakeModelCatalog())
        contract = compare_routes(load_design(), app.openapi())
        assert contract["pending"] == [] and len(contract["implemented"]) == 18
        headers = {"Origin": "http://localhost:5173"}
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as a,
            httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as b,
        ):
            response = await a.post("/api/v1/session", json={"consent_version": "v1"})
            assert response.status_code == 200, response.text
            own_sid = response.json()["id"]
            response = await b.post("/api/v1/session", json={"consent_version": "v1"})
            assert response.status_code == 200, response.text
            profile_key = {"Idempotency-Key": uuid4().hex}
            body = {"content": profile_content().model_dump(mode="json")}
            first = await a.post("/api/v1/profiles", json=body, headers=profile_key)
            assert first.status_code == 201, first.text
            p = first.json()
            updated = await a.put(
                f"/api/v1/profiles/{p['id']}",
                json={
                    "base_version": 1,
                    "content": profile_content("edited").model_dump(mode="json"),
                },
            )
            assert updated.status_code == 200 and updated.json()["version"] == 2
            confirmed = await a.post(f"/api/v1/profiles/{p['id']}/confirm", json={"version": 2})
            assert confirmed.status_code == 200 and confirmed.json()["confirmed"]
            replay = await a.post("/api/v1/profiles", json=body, headers=profile_key)
            assert replay.status_code == 201 and replay.json() == p
            response = await b.get(f"/api/v1/profiles/{p['id']}")
            assert response.status_code == 404
            key = {"Idempotency-Key": uuid4().hex}
            body = {"raw_text": "Python", "company_context": "", "model_id": "demo-model-a"}
            first = await a.post("/api/v1/jobs", json=body, headers=key)
            app.state.platform.catalog.disabled.add("demo-model-a")
            replay = await a.post("/api/v1/jobs", json=body, headers=key)
            assert first.status_code == replay.status_code == 202
            assert first.json() == replay.json()
            unavailable = await a.post(
                "/api/v1/jobs", json=body, headers={"Idempotency-Key": uuid4().hex}
            )
            assert unavailable.status_code == 422
            assert unavailable.json()["error"]["code"] == "MODEL_UNAVAILABLE"
            tid = first.json()["task_id"]
            response = await a.get(f"/api/v1/tasks/{tid}")
            assert response.status_code == 200 and response.json()["status"] == "queued"
            from app.platform.repositories import PostgreSQLRepository

            recovered_app = create_app(
                Settings(_env_file=None),
                repository=PostgreSQLRepository(engine),
                catalog=FakeModelCatalog(),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=recovered_app),
                base_url="http://test",
                headers=headers,
                cookies=a.cookies,
            ) as recovered:
                restored = await recovered.get(f"/api/v1/tasks/{tid}")
                assert restored.status_code == 200 and restored.json() == response.json()
                restored_profile = await recovered.get(f"/api/v1/profiles/{p['id']}")
                assert restored_profile.status_code == 200
                assert restored_profile.json() == confirmed.json()
            await recovered_app.state.platform.close()
            assert (await b.get(f"/api/v1/tasks/{tid}")).status_code == 404
            assert counts(engine, own_sid)["tasks"] == 1
            assert (await a.delete("/api/v1/session")).status_code == 204
            assert (await a.get(f"/api/v1/profiles/{p['id']}")).status_code == 401
            assert all(count == 0 for count in counts(engine, own_sid).values())
        await app.state.platform.close()

    asyncio.run(run())


def test_idempotency_retention_expires_without_removing_live_session(repo, engine):
    current = [datetime(2026, 10, 1, tzinfo=UTC)]
    repo.clock = lambda: current[0]
    record, token = repo.create_session()
    sid = record.public.id
    key = uuid4().hex
    first = profile(repo, sid, key=key)
    current[0] += timedelta(hours=24) - timedelta(seconds=1)
    assert profile(repo, sid, key=key) == first
    current[0] += timedelta(seconds=2)
    repo.cleanup_expired()
    assert repo.authenticate(token).public == record.public
    assert counts(engine, sid)["idempotency_keys"] == 0
    second = profile(repo, sid, key=key)
    assert first.id != second.id
    assert counts(engine, sid)["profiles"] == 2
    assert counts(engine, sid)["idempotency_keys"] == 1


def test_concurrent_new_keys_cannot_exceed_session_task_limit(repo, sid, engine):
    outcomes = race([lambda: task(repo, sid) for _ in range(3)])
    accepted = [outcome for outcome in outcomes if not isinstance(outcome, PlatformError)]
    rejected = [outcome for outcome in outcomes if isinstance(outcome, PlatformError)]
    assert len(accepted) == 2 and len(rejected) == 1
    assert (rejected[0].status, rejected[0].info.code) == (429, "RATE_LIMITED")
    assert counts(engine, sid)["tasks"] == counts(engine, sid)["idempotency_keys"] == 2
    assert len(repo.active_tasks(sid)) == 2


def test_concurrent_chat_keys_keep_one_active_task_for_profile(repo, sid, engine):
    p = profile(repo, sid)
    body = {"base_version": 1, "content": "synthetic message", "model_id": "demo-model-a"}

    def submit():
        return repo.create_task(
            sid,
            "profile_chat",
            "demo-model-a",
            snapshot(repo),
            {"profile": {"id": p.id, "version": 1}, **body},
            uuid4().hex,
            f"chat:{p.id}",
            body,
            profile_id=p.id,
        )

    outcomes = race([submit, submit])
    accepted = [outcome for outcome in outcomes if not isinstance(outcome, PlatformError)]
    rejected = [outcome for outcome in outcomes if isinstance(outcome, PlatformError)]
    assert len(accepted) == len(rejected) == 1
    assert (rejected[0].status, rejected[0].info.code) == (409, "PROFILE_BUSY")
    after = counts(engine, sid)
    assert after["tasks"] == 1 and after["idempotency_keys"] == 2  # Profile create + chat.
    assert after["profile_versions"] == 1 and after["messages"] == 0


def test_idempotency_hash_normalizes_integral_json_numbers(repo, sid, engine):
    p, key = profile(repo, sid), uuid4().hex
    body = {"base_version": 1, "content": "synthetic message", "model_id": "demo-model-a"}
    accepted = repo.create_task(
        sid,
        "profile_chat",
        "demo-model-a",
        snapshot(repo),
        {"profile": {"id": p.id, "version": 1}, **body},
        key,
        f"chat:{p.id}",
        body,
        profile_id=p.id,
    )
    assert repo.replay(sid, key, f"chat:{p.id}", {**body, "base_version": 1.0}) == accepted
    assert counts(engine, sid)["tasks"] == 1


def test_original_upload_is_deleted_by_24_hour_timer_without_session_deletion(
    repo, sid, engine, upload_dir
):
    current = [datetime.now(UTC)]
    repo.clock = lambda: current[0]
    accepted = repo.document_create(
        sid,
        b"%PDF-1.4\nsynthetic document\n%%EOF\n",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        upload_dir,
    )
    with engine.connect() as connection:
        key = connection.scalar(
            text("SELECT storage_key FROM documents WHERE session_id=:sid"), {"sid": sid}
        )
    path = upload_dir / key
    assert path.exists()
    current[0] += timedelta(hours=23, minutes=58)
    repo.retry_file_cleanup(upload_dir)
    assert path.exists()
    current[0] += timedelta(minutes=2)
    repo.cleanup_expired()
    repo.retry_file_cleanup(upload_dir)
    assert not path.exists()
    assert repo.active(sid).public.id == sid
    assert repo.owned(repo.tasks, accepted.task_id, sid).value.status == "queued"
    with engine.connect() as connection:
        stored = (
            connection.execute(
                text("SELECT storage_key,status,deleted_at FROM documents WHERE session_id=:sid"),
                {"sid": sid},
            )
            .mappings()
            .one()
        )
        assert stored["storage_key"] is None and stored["status"] == "deleted"
        assert stored["deleted_at"] == current[0]


@pytest.mark.parametrize("terminal", ["parsed", "failed"])
def test_terminal_document_handoff_is_session_scoped_and_deletes_original(
    repo, sid, engine, upload_dir, terminal
):
    repo.document_create(
        sid,
        b"%PDF-1.4\nsynthetic terminal document\n%%EOF\n",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        upload_dir,
    )
    with engine.connect() as connection:
        document = (
            connection.execute(
                text("SELECT id,storage_key FROM documents WHERE session_id=:sid"), {"sid": sid}
            )
            .mappings()
            .one()
        )
    key, did = document["storage_key"], document["id"]
    other = repo.create_session()[0].public.id
    expect_error(404, "RESOURCE_NOT_FOUND", lambda: repo.release_document(other, did, terminal))
    expect_error(422, "VALIDATION_ERROR", lambda: repo.release_document(sid, did, "processing"))
    assert (upload_dir / key).exists()
    repo.release_document(sid, did, terminal)
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT status FROM documents WHERE id=:id"), {"id": did})
            == terminal
        )
        assert (
            connection.scalar(
                text("SELECT next_attempt_at FROM file_cleanup WHERE storage_key=:key"),
                {"key": key},
            )
            <= repo.clock()
        )
    repo.retry_file_cleanup(upload_dir)
    assert not (upload_dir / key).exists()
    with engine.connect() as connection:
        document = (
            connection.execute(
                text("SELECT status,storage_key,deleted_at FROM documents WHERE id=:id"),
                {"id": did},
            )
            .mappings()
            .one()
        )
        assert document["status"] == "deleted" and document["storage_key"] is None
        assert document["deleted_at"] is not None


def test_diagnosis_uppercase_resource_ids_preserve_frozen_request_order(repo, sid, engine):
    p, first, second = profile(repo, sid), job(repo, sid), job(repo, sid)
    p = repo.confirm(repo.profiles, p.id, sid, 1)
    first = repo.confirm(repo.jobs, first.id, sid, 1)
    second = repo.confirm(repo.jobs, second.id, sid, 1)
    body = diagnosis_body(
        p.model_copy(update={"id": p.id.upper()}),
        second.model_copy(update={"id": second.id.upper()}),
        first.model_copy(update={"id": first.id.upper()}),
    )
    accepted = repo.diagnosis_create(sid, body, uuid4().hex, snapshot(repo))
    stored = repo.owned(repo.diagnoses, accepted.diagnosis_id.upper(), sid).value
    assert stored.profile.id == p.id
    assert [item.job.id for item in stored.items] == [second.id, first.id]
    with engine.connect() as connection:
        frozen = connection.scalar(
            text("SELECT input FROM tasks WHERE id=:id"), {"id": accepted.task_id}
        )
        assert frozen["profile"]["id"] == p.id
        assert [ref["id"] for ref in frozen["jobs"]] == [second.id, first.id]


def test_terminal_handoff_uses_queue_before_document_lock(repo, sid, engine, upload_dir):
    repo.document_create(
        sid,
        b"%PDF-1.4\nsynthetic lock-order document\n%%EOF\n",
        "application/pdf",
        "demo-model-a",
        uuid4().hex,
        snapshot(repo),
        upload_dir,
    )
    with engine.begin() as blocker:
        document = (
            blocker.execute(
                text("SELECT id,storage_key FROM documents WHERE session_id=:sid"), {"sid": sid}
            )
            .mappings()
            .one()
        )
        blocker.execute(
            text("SELECT storage_key FROM file_cleanup WHERE storage_key=:key FOR UPDATE"),
            {"key": document["storage_key"]},
        )
        app_name = blocker.scalar(text("SHOW application_name"))
        with ThreadPoolExecutor(max_workers=1) as workers:
            handoff = workers.submit(repo.release_document, sid, document["id"], "parsed")
            try:
                deadline = time.monotonic() + 10
                blocked = 0
                while time.monotonic() < deadline:
                    with engine.connect() as observer:
                        blocked = observer.scalar(
                            text("""SELECT count(*) FROM pg_stat_activity
                                WHERE application_name=:app AND state='active'
                                  AND wait_event_type='Lock'
                                  AND query ILIKE '%INSERT INTO file_cleanup%'
                                  AND pid <> pg_backend_pid()"""),
                            {"app": app_name},
                        )
                    if blocked:
                        break
                    time.sleep(0.02)
                assert blocked, "Terminal handoff must be waiting for the held cleanup queue row"
                # A cleaner can acquire the document while handoff waits on its queue row.
                # NOWAIT makes the old reverse lock order fail deterministically.
                with engine.begin() as cleaner:
                    cleaner.execute(
                        text("SELECT id FROM documents WHERE id=:id FOR UPDATE NOWAIT"),
                        {"id": document["id"]},
                    )
            finally:
                blocker.commit()
            handoff.result(timeout=10)
    repo.retry_file_cleanup(upload_dir)
    assert not (upload_dir / document["storage_key"]).exists()
