"""PostgreSQL transaction boundary. No process lock or in-memory resource cache.

Session share locks prevent revocation during commits; resource row locks serialize
edits. Idempotency reservations use PostgreSQL's unique index and are committed
with the resource, so a competing request observes either the winner or rollback.
"""

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy import Engine, create_engine, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.contracts import (
    Diagnosis,
    DiagnosisAccepted,
    DiagnosisItem,
    Job,
    JobContent,
    Message,
    ModelMetadata,
    Profile,
    ProfileContent,
    ProfileCreate,
    ResourceVersion,
    Session,
    Task,
    TaskAccepted,
)
from app.contracts.models import json_key
from app.platform.errors import PlatformError, conflict, expired, missing
from app.platform.repositories import schema as db
from app.platform.repositories.memory import Owned, SessionRecord, Versioned, new_id, timestamp
from app.platform.validation import invalid, validate_job, validate_profile

# Reserve one sweep interval so a healthy 60-second cleanup loop runs by 24h.
FILE_CLEANUP_DELAY = timedelta(hours=24) - timedelta(minutes=1)


def uid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise missing() from None


class PostgreSQLRepository:
    is_fake = False
    profiles, jobs, tasks, diagnoses = "profiles", "jobs", "tasks", "diagnoses"

    def __init__(self, engine: Engine | str, clock: Callable[[], datetime] | None = None):
        if isinstance(engine, str):
            if engine.startswith("postgresql://"):
                engine = "postgresql+psycopg://" + engine[len("postgresql://") :]
            if not engine.startswith("postgresql+psycopg://"):
                raise ValueError("PostgreSQL with psycopg is required")
            engine = create_engine(engine, hide_parameters=True, pool_pre_ping=True)
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL is required")
        self.engine = engine
        self.clock = clock or (lambda: datetime.now(UTC))

    def now(self):
        return timestamp(self.clock())

    def close(self):
        self.engine.dispose()

    def _active(self, connection, sid, exclusive=False):
        row = (
            connection.execute(
                select(db.sessions)
                .where(db.sessions.c.id == uid(sid))
                .with_for_update(read=not exclusive)
            )
            .mappings()
            .first()
        )
        if row is None or row["revoked_at"] is not None or row["expires_at"] <= self.clock():
            raise expired()
        return row

    def _session(self, row):
        return SessionRecord(
            Session(id=row["id"], expires_at=timestamp(row["expires_at"])),
            row["token_hash"],
            row["expires_at"],
        )

    def create_session(self):
        token = secrets.token_urlsafe(32)
        now = self.clock()
        values = dict(
            id=new_id(),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            consent_version="v1",
            expires_at=now + timedelta(days=7),
            revoked_at=None,
            created_at=now,
        )
        with self.engine.begin() as connection:
            connection.execute(insert(db.sessions).values(**values))
        return self._session(values), token

    def active(self, sid):
        with self.engine.begin() as connection:
            return self._session(self._active(connection, sid))

    def authenticate(self, token):
        if not token:
            raise expired()
        with self.engine.begin() as connection:
            sid = connection.execute(
                select(db.sessions.c.id).where(
                    db.sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest()
                )
            ).scalar_one_or_none()
            if sid is None:
                raise expired()
            return self._session(self._active(connection, sid))

    def _tables(self, table):
        if table == self.profiles:
            return db.profiles, db.profile_versions, "profile_id", Profile
        if table == self.jobs:
            return db.jobs, db.job_versions, "job_id", Job
        raise ValueError("Expected a versioned repository")

    def _parent(self, connection, table, rid, sid, lock=False):
        parent, _, _, _ = self._tables(table)
        statement = select(parent).where(parent.c.id == uid(rid), parent.c.session_id == uid(sid))
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().first()
        if row is None:
            raise missing()
        return row

    def _version(self, connection, table, rid, sid, version=None, parent=None):
        _, versions, fk, model = self._tables(table)
        parent = parent if parent is not None else self._parent(connection, table, rid, sid)
        row = (
            connection.execute(
                select(versions).where(
                    versions.c[fk] == uid(rid),
                    versions.c.session_id == uid(sid),
                    versions.c.version
                    == (parent["latest_version"] if version is None else version),
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise missing()
        values = dict(
            id=uid(rid),
            version=row["version"],
            confirmed=row["confirmed_at"] is not None,
            content=row["content"],
            created_at=timestamp(row["created_at"]),
        )
        if table == self.jobs:
            values["raw_text"] = row["raw_text"]
        return model.model_validate(values)

    def version(self, table, rid, sid, version=None):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            return self._version(connection, table, rid, sid, version)

    def _validate(self, table, content, raw_text=None):
        if table == self.profiles:
            value = ProfileContent.model_validate(
                content.model_dump() if hasattr(content, "model_dump") else content
            )
            validate_profile(value, self.now()[:7])
        else:
            value = JobContent.model_validate(
                content.model_dump() if hasattr(content, "model_dump") else content
            )
            validate_job(value, raw_text)
        return value.model_dump(mode="json")

    def _create_versioned(
        self, connection, table, sid, content, raw_text=None, task_id=None, rid=None
    ):
        parent, versions, fk, _ = self._tables(table)
        rid, now = rid or new_id(), self.clock()
        content = self._validate(table, content, raw_text)
        if task_id:
            self._owned_task(connection, task_id, sid)
        connection.execute(
            insert(parent).values(id=rid, session_id=uid(sid), latest_version=1, created_at=now)
        )
        values = dict(
            session_id=uid(sid),
            version=1,
            content=content,
            confirmed_at=None,
            created_by_task_id=task_id,
            created_at=now,
            **{fk: rid},
        )
        if table == self.jobs:
            values["raw_text"] = raw_text
        connection.execute(insert(versions).values(**values))
        return self._version(connection, table, rid, sid, 1)

    def create_job(self, sid, raw_text, content, created_by_task_id=None):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            return self._create_versioned(
                connection, self.jobs, sid, content, raw_text, created_by_task_id
            )

    def _append(
        self, connection, table, rid, sid, base, content, raw_text=None, created_by_task_id=None
    ):
        parent_table, versions, fk, _ = self._tables(table)
        parent = self._parent(connection, table, rid, sid, lock=True)
        if parent["latest_version"] != base:
            raise conflict()
        content = self._validate(table, content, raw_text)
        if created_by_task_id:
            self._owned_task(connection, created_by_task_id, sid)
        values = dict(
            session_id=uid(sid),
            version=base + 1,
            content=content,
            confirmed_at=None,
            created_by_task_id=created_by_task_id,
            created_at=self.clock(),
            **{fk: uid(rid)},
        )
        if table == self.jobs:
            values["raw_text"] = raw_text
        connection.execute(insert(versions).values(**values))
        connection.execute(
            update(parent_table)
            .where(parent_table.c.id == uid(rid), parent_table.c.session_id == uid(sid))
            .values(latest_version=base + 1)
        )
        return self._version(connection, table, rid, sid, base + 1)

    def append(self, table, rid, sid, base, **changes):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            return self._append(connection, table, rid, sid, base, **changes)

    def confirm(self, table, rid, sid, version):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            parent = self._parent(connection, table, rid, sid, lock=True)
            if parent["latest_version"] != version:
                raise conflict()
            current = self._version(connection, table, rid, sid, version, parent)
            self._validate(table, current.content, getattr(current, "raw_text", None))
            _, versions, fk, _ = self._tables(table)
            connection.execute(
                update(versions)
                .where(
                    versions.c[fk] == uid(rid),
                    versions.c.session_id == uid(sid),
                    versions.c.version == version,
                    versions.c.confirmed_at.is_(None),
                )
                .values(confirmed_at=self.clock())
            )
            return self._version(connection, table, rid, sid, version, parent)

    @staticmethod
    def request_hash(body):
        return hashlib.sha256(json_key(body).encode("utf-8")).hexdigest()

    def _key(self, connection, sid, key, operation, body):
        row = (
            connection.execute(
                select(db.idempotency_keys).where(
                    db.idempotency_keys.c.session_id == uid(sid),
                    db.idempotency_keys.c.key == key,
                )
            )
            .mappings()
            .first()
        )
        if row and row["created_at"] <= self.clock() - timedelta(hours=24):
            connection.execute(
                delete(db.idempotency_keys).where(
                    db.idempotency_keys.c.session_id == uid(sid),
                    db.idempotency_keys.c.key == key,
                    db.idempotency_keys.c.created_at <= self.clock() - timedelta(hours=24),
                )
            )
            row = None
        if row and (
            row["operation"] != operation or row["request_hash"] != self.request_hash(body)
        ):
            raise PlatformError(409, "IDEMPOTENCY_CONFLICT", "幂等键已用于不同请求")
        return row

    def _replay(self, connection, row, sid):
        operation, rid = row["operation"], row["resource_id"]
        if operation == "profile_create":
            # The first response was an unconfirmed version 1, even after later edits/confirmation.
            return self._version(connection, self.profiles, rid, sid, 1).model_copy(
                update={"confirmed": False}
            )
        if operation == "diagnosis":
            diagnosis = (
                connection.execute(
                    select(db.diagnoses).where(
                        db.diagnoses.c.id == rid, db.diagnoses.c.session_id == uid(sid)
                    )
                )
                .mappings()
                .one()
            )
            return DiagnosisAccepted(task_id=diagnosis["task_id"], diagnosis_id=rid)
        return TaskAccepted(task_id=rid)

    def replay(self, sid, key, operation, body):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            row = self._key(connection, sid, key, operation, body)
            return self._replay(connection, row, sid) if row else None

    def _claim(self, connection, sid, key, operation, body, resource_type, rid):
        if not 16 <= len(key) <= 128:
            raise invalid()
        row = self._key(connection, sid, key, operation, body)
        if row:
            return self._replay(connection, row, sid)
        inserted = connection.execute(
            pg_insert(db.idempotency_keys)
            .values(
                session_id=uid(sid),
                key=key,
                operation=operation,
                request_hash=self.request_hash(body),
                resource_type=resource_type,
                resource_id=rid,
                created_at=self.clock(),
            )
            .on_conflict_do_nothing(index_elements=["session_id", "key"])
            .returning(db.idempotency_keys.c.key)
        ).first()
        if inserted is None:
            row = self._key(connection, sid, key, operation, body)
            return self._replay(connection, row, sid)
        return None

    def profile_create(self, sid, body: ProfileCreate, key):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            rid = new_id()
            cached = self._claim(connection, sid, key, "profile_create", body, "profile", rid)
            if cached:
                return cached
            return self._create_versioned(connection, self.profiles, sid, body.content, rid=rid)

    def _owned_task(self, connection, rid, sid):
        row = (
            connection.execute(
                select(db.tasks).where(db.tasks.c.id == uid(rid), db.tasks.c.session_id == uid(sid))
            )
            .mappings()
            .first()
        )
        if row is None:
            raise missing()
        return row

    def _task_dto(self, row):
        return Task.model_validate(
            {
                k: timestamp(row[k]) if k in {"created_at", "updated_at"} else row[k]
                for k in Task.model_fields
            }
        )

    def _new_task(self, connection, sid, kind, model_id, model_snapshot, data, task_id):
        if kind not in {"profile_chat", "document_parse", "job_parse", "diagnosis"}:
            raise invalid()
        snapshot = ModelMetadata.model_validate(model_snapshot)
        if snapshot.model_id != model_id:
            raise invalid()
        count = connection.execute(
            select(func.count())
            .select_from(db.tasks)
            .where(db.tasks.c.session_id == uid(sid), db.tasks.c.status.in_(["queued", "running"]))
        ).scalar_one()
        if count >= 2:
            raise PlatformError(429, "RATE_LIMITED", "最多同时处理两个任务", retry_after=2)
        now = self.clock()
        connection.execute(
            insert(db.tasks).values(
                id=task_id,
                session_id=uid(sid),
                kind=kind,
                status="queued",
                input=data,
                result=None,
                error=None,
                model_id=model_id,
                model_snapshot=snapshot.model_dump(mode="json"),
                attempt=0,
                lease_token=None,
                lease_until=None,
                heartbeat_at=None,
                deadline_at=now + timedelta(minutes=5),
                created_at=now,
                updated_at=now,
            )
        )

    def create_task(
        self, sid, kind, model_id, model_snapshot, input, key, operation, body, profile_id=None
    ):
        expected = {
            "job_parse": "job_create",
            "profile_chat": f"chat:{uid(profile_id)}" if profile_id else "",
            "document_parse": "document",
        }
        if expected.get(kind) != operation:
            raise invalid()
        with self.engine.begin() as connection:
            self._active(connection, sid, exclusive=True)
            tid = new_id()
            cached = self._claim(connection, sid, key, operation, body, "task", tid)
            if cached:
                return cached
            if kind == "job_parse" and not input.get("raw_text", "").strip():
                raise invalid()
            if profile_id:
                parent = self._parent(connection, self.profiles, profile_id, sid, lock=True)
                if parent["latest_version"] != input["base_version"]:
                    raise conflict()
                active = (
                    connection.execute(
                        select(db.tasks.c.input).where(
                            db.tasks.c.session_id == uid(sid),
                            db.tasks.c.kind == "profile_chat",
                            db.tasks.c.status.in_(["queued", "running"]),
                        )
                    )
                    .scalars()
                    .all()
                )
                if any(item.get("profile", {}).get("id") == uid(profile_id) for item in active):
                    raise PlatformError(409, "PROFILE_BUSY", "该档案已有任务，请等待后重试")
                rounds = connection.execute(
                    select(func.count())
                    .select_from(db.messages)
                    .where(db.messages.c.session_id == uid(sid), db.messages.c.role == "user")
                ).scalar_one()
                if rounds + len(active) >= 50:
                    raise invalid()
            self._new_task(connection, sid, kind, model_id, model_snapshot, input, tid)
            return TaskAccepted(task_id=tid)

    def diagnosis_create(self, sid, body, key, model_snapshot):
        with self.engine.begin() as connection:
            self._active(connection, sid, exclusive=True)
            did, tid = new_id(), new_id()
            cached = self._claim(connection, sid, key, "diagnosis", body, "diagnosis", did)
            if cached:
                return cached
            profile = self._version(
                connection, self.profiles, body.profile.id, sid, body.profile.version
            )
            jobs = [self._version(connection, self.jobs, r.id, sid, r.version) for r in body.jobs]
            if len({job.id for job in jobs}) != len(jobs):
                raise invalid()
            if not profile.confirmed or any(not job.confirmed for job in jobs):
                raise PlatformError(422, "UNCONFIRMED_VERSION", "请先确认档案和全部岗位版本")
            if any(not any(not r.ignored for r in job.content.requirements) for job in jobs):
                raise PlatformError(422, "NO_SCORABLE_REQUIREMENTS", "岗位没有可评分要求")
            frozen_input = body.model_dump(mode="json")
            frozen_input["profile"]["id"] = profile.id
            frozen_input["jobs"] = [{"id": job.id, "version": job.version} for job in jobs]
            self._new_task(
                connection,
                sid,
                "diagnosis",
                body.model_id,
                model_snapshot,
                frozen_input,
                tid,
            )
            now = self.clock()
            connection.execute(
                insert(db.diagnoses).values(
                    id=did,
                    session_id=uid(sid),
                    task_id=tid,
                    profile_id=profile.id,
                    profile_version=profile.version,
                    model_id=body.model_id,
                    created_at=now,
                )
            )
            for job in jobs:
                connection.execute(
                    insert(db.diagnosis_items).values(
                        id=new_id(),
                        session_id=uid(sid),
                        diagnosis_id=did,
                        job_id=job.id,
                        job_version=job.version,
                        status="pending",
                        score_result=None,
                        report=None,
                        error=None,
                        model_metadata=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            return DiagnosisAccepted(task_id=tid, diagnosis_id=did)

    def owned(self, table, rid, sid):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            if table in {self.profiles, self.jobs}:
                value = self._version(connection, table, rid, sid)
                messages = []
                if table == self.profiles:
                    rows = connection.execute(
                        select(db.messages)
                        .where(
                            db.messages.c.session_id == uid(sid),
                            db.messages.c.profile_id == uid(rid),
                        )
                        .order_by(db.messages.c.created_at, db.messages.c.role.desc())
                    ).mappings()
                    messages = [
                        Message(
                            id=r["id"],
                            role=r["role"],
                            content=r["content"],
                            created_at=timestamp(r["created_at"]),
                        )
                        for r in rows
                    ]
                return Versioned(uid(sid), [value], messages)
            if table == self.tasks:
                return Owned(uid(sid), self._task_dto(self._owned_task(connection, rid, sid)))
            if table != self.diagnoses:
                raise ValueError("Unknown repository")
            diagnosis = (
                connection.execute(
                    select(db.diagnoses).where(
                        db.diagnoses.c.id == uid(rid), db.diagnoses.c.session_id == uid(sid)
                    )
                )
                .mappings()
                .first()
            )
            if diagnosis is None:
                raise missing()
            task = self._owned_task(connection, diagnosis["task_id"], sid)
            rows = (
                connection.execute(
                    select(db.diagnosis_items)
                    .where(
                        db.diagnosis_items.c.session_id == uid(sid),
                        db.diagnosis_items.c.diagnosis_id == uid(rid),
                    )
                    .order_by(db.diagnosis_items.c.created_at, db.diagnosis_items.c.id)
                )
                .mappings()
                .all()
            )
            # Preserve request order from the immutable task input, not UUID order.
            order = {r["id"]: i for i, r in enumerate(task["input"]["jobs"])}
            rows.sort(key=lambda r: order[r["job_id"]])
            items = [
                DiagnosisItem.model_validate(
                    dict(
                        id=r["id"],
                        job={"id": r["job_id"], "version": r["job_version"]},
                        **{
                            k: r[k]
                            for k in ("status", "score_result", "report", "error", "model_metadata")
                        },
                    )
                )
                for r in rows
            ]
            value = Diagnosis(
                id=uid(rid),
                task_id=task["id"],
                status=task["status"],
                profile=ResourceVersion(
                    id=diagnosis["profile_id"], version=diagnosis["profile_version"]
                ),
                model_id=diagnosis["model_id"],
                items=items,
                created_at=timestamp(diagnosis["created_at"]),
            )
            return Owned(uid(sid), value)

    def active_tasks(self, sid):
        with self.engine.begin() as connection:
            self._active(connection, sid)
            return [
                self._task_dto(r)
                for r in connection.execute(
                    select(db.tasks).where(
                        db.tasks.c.session_id == uid(sid),
                        db.tasks.c.status.in_(["queued", "running"]),
                    )
                ).mappings()
            ]

    def commit_profile_task(self, sid, task_id, rid, base, content, user_text, assistant_text):
        """Atomic result write boundary; worker lease validation is added by JOB-01."""
        with self.engine.begin() as connection:
            self._active(connection, sid, exclusive=True)
            task = self._owned_task(connection, task_id, sid)
            if task["kind"] != "profile_chat" or task["input"].get("profile", {}).get("id") != uid(
                rid
            ):
                raise missing()
            if task["input"].get("base_version") != base:
                raise conflict()
            if task["status"] == "succeeded":
                return self._version(connection, self.profiles, rid, sid, task["result"]["version"])
            if task["status"] not in {"queued", "running"}:
                raise conflict()
            profile = self._append(
                connection, self.profiles, rid, sid, base, content, created_by_task_id=task_id
            )
            now = self.clock()
            for role, text in (("user", user_text), ("assistant", assistant_text)):
                connection.execute(
                    insert(db.messages).values(
                        id=new_id(),
                        session_id=uid(sid),
                        profile_id=uid(rid),
                        task_id=uid(task_id),
                        role=role,
                        content=text,
                        created_at=now,
                    )
                )
            connection.execute(
                update(db.tasks)
                .where(db.tasks.c.id == uid(task_id), db.tasks.c.session_id == uid(sid))
                .values(
                    status="succeeded",
                    updated_at=now,
                    result={
                        "resource_type": "profile",
                        "resource_id": uid(rid),
                        "version": profile.version,
                        "assistant_message": assistant_text,
                    },
                )
            )
            return profile

    @staticmethod
    def document_fingerprint(data, model_id, media_type):
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "model_id": model_id,
            "media_type": media_type,
        }

    def document_create(
        self,
        sid,
        data,
        media_type,
        model_id,
        key,
        model_snapshot,
        upload_dir,
        *,
        original_name="upload",
    ):
        if len(data) > 10 * 1024 * 1024:
            raise PlatformError(413, "FILE_TOO_LARGE", "文件超过 10 MiB")
        directory = Path(upload_dir)
        fingerprint = self.document_fingerprint(data, model_id, media_type)
        storage_key = None
        try:
            with self.engine.begin() as connection:
                self._active(connection, sid, exclusive=True)
                tid, did = new_id(), new_id()
                cached = self._claim(connection, sid, key, "document", fingerprint, "task", tid)
                if cached:
                    return cached
                storage_key = new_id()
                # Commit a PII-free orphan-cleanup reservation BEFORE touching disk.
                # If this process dies before the resource transaction commits,
                # the separately durable row still schedules eventual deletion.
                with self.engine.begin() as cleanup_connection:
                    self._queue_file(
                        cleanup_connection, storage_key, due=self.clock() + FILE_CLEANUP_DELAY
                    )
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                descriptor = os.open(
                    directory / storage_key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                now = self.clock()
                connection.execute(
                    insert(db.documents).values(
                        id=did,
                        session_id=uid(sid),
                        profile_id=None,
                        storage_key=storage_key,
                        original_name=original_name,
                        media_type=media_type,
                        size_bytes=len(data),
                        status="stored",
                        deleted_at=None,
                        created_at=now,
                    )
                )
                self._new_task(
                    connection,
                    sid,
                    "document_parse",
                    model_id,
                    model_snapshot,
                    {"document_id": did, "media_type": media_type},
                    tid,
                )
                return TaskAccepted(task_id=tid)
        except Exception:
            if storage_key:
                try:
                    (directory / storage_key).unlink(missing_ok=True)
                except OSError:
                    with self.engine.begin() as connection:
                        self._queue_file(connection, storage_key)
            raise

    def _queue_file(self, connection, storage_key, due=None):
        now = self.clock()
        statement = pg_insert(db.file_cleanup).values(
            storage_key=storage_key, created_at=now, attempt=0, next_attempt_at=due or now
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["storage_key"],
                set_={"next_attempt_at": func.least(db.file_cleanup.c.next_attempt_at, due or now)},
            )
        )

    def release_document(self, sid, document_id, status="parsed"):
        """Hand terminal originals to the durable cleanup queue (worker consumer)."""
        if status not in {"parsed", "failed"}:
            raise invalid()
        with self.engine.begin() as connection:
            self._active(connection, sid)
            row = (
                connection.execute(
                    select(db.documents).where(
                        db.documents.c.id == uid(document_id), db.documents.c.session_id == uid(sid)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise missing()
            if row["storage_key"]:
                # All file lifecycle transactions lock queue -> document. The
                # cleanup loop uses the same order, avoiding a lock inversion.
                self._queue_file(connection, row["storage_key"])
                connection.execute(
                    update(db.documents)
                    .where(
                        db.documents.c.id == uid(document_id),
                        db.documents.c.session_id == uid(sid),
                        db.documents.c.storage_key == row["storage_key"],
                    )
                    .values(status=status)
                )

    def _revoke(self, connection, sid):
        row = (
            connection.execute(
                select(db.sessions).where(db.sessions.c.id == uid(sid)).with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None:
            return
        connection.execute(
            update(db.sessions)
            .where(db.sessions.c.id == uid(sid))
            .values(revoked_at=row["revoked_at"] or self.clock())
        )
        for storage_key in connection.execute(
            select(db.documents.c.storage_key).where(
                db.documents.c.session_id == uid(sid), db.documents.c.storage_key.is_not(None)
            )
        ).scalars():
            self._queue_file(connection, storage_key)
        for table in (
            db.diagnosis_items,
            db.diagnoses,
            db.messages,
            db.documents,
            db.profile_versions,
            db.job_versions,
            db.profiles,
            db.jobs,
            db.tasks,
            db.idempotency_keys,
        ):
            connection.execute(delete(table).where(table.c.session_id == uid(sid)))

    def revoke(self, sid):
        with self.engine.begin() as connection:
            self._revoke(connection, sid)

    def cleanup_expired(self):
        with self.engine.begin() as connection:
            ids = (
                connection.execute(
                    select(db.sessions.c.id)
                    .where(
                        or_(
                            db.sessions.c.expires_at <= self.clock(),
                            db.sessions.c.revoked_at.is_not(None),
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            for sid in ids:
                self._revoke(connection, sid)
                connection.execute(delete(db.sessions).where(db.sessions.c.id == sid))
            connection.execute(
                delete(db.idempotency_keys).where(
                    db.idempotency_keys.c.created_at <= self.clock() - timedelta(hours=24)
                )
            )
            return len(ids)

    def retry_file_cleanup(self, upload_dir):
        cleaned = 0
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(db.file_cleanup)
                    .where(db.file_cleanup.c.next_attempt_at <= self.clock())
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for row in rows:
                key = row["storage_key"]
                # Storage keys are generated UUIDs; reject injected paths before filesystem I/O.
                if uid(key) != key:
                    continue
                try:
                    (Path(upload_dir) / key).unlink(missing_ok=True)
                except OSError:
                    connection.execute(
                        update(db.file_cleanup)
                        .where(db.file_cleanup.c.storage_key == key)
                        .values(
                            attempt=row["attempt"] + 1,
                            next_attempt_at=self.clock() + timedelta(minutes=1),
                        )
                    )
                else:
                    connection.execute(
                        delete(db.file_cleanup).where(db.file_cleanup.c.storage_key == key)
                    )
                    connection.execute(
                        update(db.documents)
                        .where(db.documents.c.storage_key == key)
                        .values(storage_key=None, status="deleted", deleted_at=self.clock())
                    )
                    cleaned += 1
        return cleaned
