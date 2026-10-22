"""Short PostgreSQL worker transactions with lease fencing and frozen inputs.

No port/model work runs inside these transactions. The session row is always
locked before the task; file cleanup continues to lock its queue before documents.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import insert, or_, select, update

from app.contracts import (
    Diagnosis,
    DiagnosisItem,
    Job,
    Message,
    ModelMetadata,
    Profile,
    ReportContent,
    ResourceVersion,
    ScoreResult,
)
from app.platform.errors import PlatformError, missing, task_error
from app.platform.repositories import schema as db
from app.platform.repositories.memory import new_id, timestamp
from app.platform.repositories.postgres import uid

LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 15
MAX_ATTEMPTS = 2
TERMINAL_ITEMS = {"succeeded", "score_only", "failed"}


class LeaseLost(Exception):
    """Internal cancellation: the caller must stop and discard its result."""


@dataclass(frozen=True)
class Lease:
    task_id: str
    session_id: str
    token: str
    kind: str
    input: dict[str, Any]
    model_id: str
    model_snapshot: dict[str, Any]
    deadline_at: datetime
    attempt: int


@dataclass(frozen=True)
class Work:
    profile: Profile | None = None
    history: tuple[Message, ...] = ()
    document: dict[str, Any] | None = None
    diagnosis: Diagnosis | None = None
    jobs: tuple[Job, ...] = ()


def _dump(model, value):
    """Revalidate even model_construct results before writing JSONB."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", warnings=False)
    return model.model_validate(value).model_dump(mode="json")


def _error(value=None, *, timeout=False):
    return task_error(TimeoutError() if timeout else value).model_dump(mode="json")


class JobStore:
    def __init__(self, repository):
        self.repo = repository
        self.engine = repository.engine

    def _lease(self, row):
        return Lease(
            task_id=row["id"],
            session_id=row["session_id"],
            token=row["lease_token"],
            kind=row["kind"],
            input=row["input"],
            model_id=row["model_id"],
            model_snapshot=row["model_snapshot"],
            deadline_at=row["deadline_at"],
            attempt=row["attempt"],
        )

    def _live(self, session, row):
        now = self.repo.clock()
        if session["revoked_at"] is not None or session["expires_at"] <= now:
            raise LeaseLost()
        if row["lease_until"] is None or row["lease_until"] <= now or row["deadline_at"] <= now:
            raise LeaseLost()

    @contextmanager
    def _transaction(self, lease):
        with self.engine.begin() as connection:
            try:
                session = self.repo._active(connection, lease.session_id)
            except PlatformError:
                raise LeaseLost() from None
            row = (
                connection.execute(
                    select(db.tasks)
                    .where(
                        db.tasks.c.id == uid(lease.task_id),
                        db.tasks.c.session_id == uid(lease.session_id),
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None or row["status"] != "running" or row["lease_token"] != lease.token:
                raise LeaseLost()
            self._live(session, row)
            yield connection, row
            # Time can advance while waiting on a parent/item lock. Roll back all
            # writes if this operation no longer fits the session/lease deadline.
            self._live(session, row)

    def _candidates(self):
        now = self.repo.clock()
        return (
            select(db.tasks.c.id, db.tasks.c.session_id)
            .where(
                db.tasks.c.status.in_(["queued", "running"]),
                or_(
                    db.tasks.c.status == "queued",
                    db.tasks.c.lease_until <= now,
                    db.tasks.c.lease_until.is_(None),
                    db.tasks.c.deadline_at <= now,
                ),
            )
            .order_by(db.tasks.c.created_at, db.tasks.c.id)
        )

    def _lock_candidate(self, connection, candidate):
        session = (
            connection.execute(
                select(db.sessions)
                .where(db.sessions.c.id == candidate["session_id"])
                .with_for_update(read=True, skip_locked=True)
            )
            .mappings()
            .first()
        )
        if (
            session is None
            or session["revoked_at"] is not None
            or session["expires_at"] <= self.repo.clock()
        ):
            return None
        row = (
            connection.execute(
                select(db.tasks)
                .where(
                    db.tasks.c.id == candidate["id"],
                    db.tasks.c.session_id == candidate["session_id"],
                )
                .with_for_update(skip_locked=True)
            )
            .mappings()
            .first()
        )
        if row is None or row["status"] not in {"queued", "running"}:
            return None
        now = self.repo.clock()
        if (
            row["status"] == "running"
            and row["lease_until"] is not None
            and row["lease_until"] > now
            and row["deadline_at"] > now
        ):
            return None
        return row

    def _terminal_reason(self, row):
        if row["deadline_at"] <= self.repo.clock():
            return _error(timeout=True)
        if row["attempt"] >= MAX_ATTEMPTS:
            return _error()
        return None

    def reap(self):
        """Converge deadlines/exhausted leases without taking new work."""
        count = 0
        with self.engine.connect() as connection:
            candidates = connection.execute(self._candidates()).mappings().all()
        for candidate in candidates:
            with self.engine.begin() as connection:
                row = self._lock_candidate(connection, candidate)
                if row is not None and (reason := self._terminal_reason(row)) is not None:
                    self._fail_locked(connection, row, reason)
                    count += 1
        return count

    def claim(self):
        self.reap()
        with self.engine.connect() as connection:
            candidates = connection.execute(self._candidates()).mappings().all()
        for candidate in candidates:
            with self.engine.begin() as connection:
                row = self._lock_candidate(connection, candidate)
                if row is None:
                    continue
                if (reason := self._terminal_reason(row)) is not None:
                    self._fail_locked(connection, row, reason)
                    continue
                now = self.repo.clock()
                values = dict(
                    status="running",
                    attempt=row["attempt"] + 1,
                    lease_token=new_id(),
                    heartbeat_at=now,
                    lease_until=min(now + timedelta(seconds=LEASE_SECONDS), row["deadline_at"]),
                    updated_at=now,
                )
                connection.execute(
                    update(db.tasks)
                    .where(db.tasks.c.id == row["id"], db.tasks.c.session_id == row["session_id"])
                    .values(**values)
                )
                return self._lease({**row, **values})
        return None

    def heartbeat(self, lease):
        try:
            with self._transaction(lease) as (connection, row):
                now = self.repo.clock()
                connection.execute(
                    update(db.tasks)
                    .where(db.tasks.c.id == row["id"], db.tasks.c.session_id == row["session_id"])
                    .values(
                        heartbeat_at=now,
                        lease_until=min(now + timedelta(seconds=LEASE_SECONDS), row["deadline_at"]),
                        updated_at=now,
                    )
                )
            return True
        except LeaseLost:
            return False

    def _diagnosis(self, connection, row):
        diagnosis = (
            connection.execute(
                select(db.diagnoses).where(
                    db.diagnoses.c.task_id == row["id"],
                    db.diagnoses.c.session_id == row["session_id"],
                )
            )
            .mappings()
            .first()
        )
        if diagnosis is None:
            raise missing()
        return diagnosis

    def _items(self, connection, row, *, lock=False):
        diagnosis = self._diagnosis(connection, row)
        query = (
            select(db.diagnosis_items)
            .where(
                db.diagnosis_items.c.diagnosis_id == diagnosis["id"],
                db.diagnosis_items.c.session_id == row["session_id"],
            )
            .order_by(db.diagnosis_items.c.id)
        )
        if lock:
            query = query.with_for_update()
        return diagnosis, connection.execute(query).mappings().all()

    def _item_dto(self, row):
        return DiagnosisItem.model_validate(
            dict(
                id=row["id"],
                job={"id": row["job_id"], "version": row["job_version"]},
                **{
                    key: row[key]
                    for key in ("status", "score_result", "report", "error", "model_metadata")
                },
            )
        )

    def load(self, lease):
        with self._transaction(lease) as (connection, row):
            sid, data = row["session_id"], row["input"]
            if row["kind"] == "profile_chat":
                profile = self.repo._version(
                    connection, self.repo.profiles, data["profile"]["id"], sid, data["base_version"]
                )
                messages = (
                    connection.execute(
                        select(db.messages)
                        .where(
                            db.messages.c.session_id == sid,
                            db.messages.c.profile_id == profile.id,
                            db.messages.c.role == "user",
                        )
                        .order_by(db.messages.c.created_at.desc(), db.messages.c.id.desc())
                        .limit(10)
                    )
                    .mappings()
                    .all()
                )
                return Work(
                    profile=profile,
                    history=tuple(
                        Message(
                            id=r["id"],
                            role=r["role"],
                            content=r["content"],
                            created_at=timestamp(r["created_at"]),
                        )
                        for r in reversed(messages)
                    ),
                )
            if row["kind"] == "document_parse":
                document = (
                    connection.execute(
                        select(db.documents).where(
                            db.documents.c.id == uid(data["document_id"]),
                            db.documents.c.session_id == sid,
                        )
                    )
                    .mappings()
                    .first()
                )
                if document is None or not document["storage_key"]:
                    raise missing()
                connection.execute(
                    update(db.documents)
                    .where(db.documents.c.id == document["id"], db.documents.c.session_id == sid)
                    .values(status="processing")
                )
                return Work(document=dict(document))
            if row["kind"] == "diagnosis":
                diagnosis, items = self._items(connection, row)
                order = {r["id"]: i for i, r in enumerate(data["jobs"])}
                items.sort(key=lambda r: order[r["job_id"]])
                profile = self.repo._version(
                    connection,
                    self.repo.profiles,
                    diagnosis["profile_id"],
                    sid,
                    diagnosis["profile_version"],
                )
                jobs = tuple(
                    self.repo._version(
                        connection, self.repo.jobs, r["job_id"], sid, r["job_version"]
                    )
                    for r in items
                )
                dto = Diagnosis(
                    id=diagnosis["id"],
                    task_id=row["id"],
                    status=row["status"],
                    profile=ResourceVersion(id=profile.id, version=profile.version),
                    model_id=row["model_id"],
                    items=[self._item_dto(r) for r in items],
                    created_at=timestamp(diagnosis["created_at"]),
                )
                return Work(profile=profile, diagnosis=dto, jobs=jobs)
            return Work()

    def _item(self, connection, row, item_id):
        _, items = self._items(connection, row, lock=True)
        for item in items:
            if item["id"] == uid(item_id):
                return item
        raise missing()

    def _update_item(self, connection, item, **values):
        values["updated_at"] = self.repo.clock()
        connection.execute(
            update(db.diagnosis_items)
            .where(
                db.diagnosis_items.c.id == item["id"],
                db.diagnosis_items.c.session_id == item["session_id"],
            )
            .values(**values)
        )
        return self._item_dto({**item, **values})

    def start_item(self, lease, item_id):
        with self._transaction(lease) as (connection, row):
            item = self._item(connection, row, item_id)
            if item["status"] in TERMINAL_ITEMS:
                return self._item_dto(item)
            return self._update_item(
                connection, item, status="reporting" if item["score_result"] else "scoring"
            )

    def save_score(self, lease, item_id, score):
        score = _dump(ScoreResult, score)
        with self._transaction(lease) as (connection, row):
            item = self._item(connection, row, item_id)
            if item["status"] in TERMINAL_ITEMS or item["score_result"] is not None:
                return self._item_dto(item)
            return self._update_item(connection, item, score_result=score, status="reporting")

    def finish_item(self, lease, item_id, *, report=None, metadata=None, error=None):
        report = _dump(ReportContent, report) if report is not None else None
        metadata = _dump(ModelMetadata, metadata) if metadata is not None else None
        with self._transaction(lease) as (connection, row):
            item = self._item(connection, row, item_id)
            if item["status"] in TERMINAL_ITEMS:
                return self._item_dto(item)
            if report is not None and (item["score_result"] is None or metadata is None):
                raise ValueError("A report requires persisted scoring and model metadata")
            if metadata is not None and metadata["model_id"] != row["model_id"]:
                raise ValueError("Model selection differs from the frozen task")
            success = report is not None
            return self._update_item(
                connection,
                item,
                status="succeeded"
                if success
                else ("score_only" if item["score_result"] else "failed"),
                report=report,
                model_metadata=metadata if success else None,
                error=None if success else _error(error),
            )

    def _complete(self, connection, row, status, result=None, error=None):
        values = dict(status=status, result=result, error=error, updated_at=self.repo.clock())
        connection.execute(
            update(db.tasks)
            .where(db.tasks.c.id == row["id"], db.tasks.c.session_id == row["session_id"])
            .values(**values)
        )
        return self.repo._task_dto({**row, **values})

    def _aggregate(self, connection, row, error=None):
        diagnosis, items = self._items(connection, row, lock=True)
        if any(item["status"] not in TERMINAL_ITEMS for item in items):
            raise ValueError("Cannot finalize while a diagnosis item is unfinished")
        status = (
            "succeeded"
            if all(item["status"] == "succeeded" for item in items)
            else (
                "partial" if any(item["score_result"] is not None for item in items) else "failed"
            )
        )
        result = {
            "resource_type": "diagnosis",
            "resource_id": diagnosis["id"],
            "version": None,
            "assistant_message": None,
        }
        if status == "failed" and error is None:
            # Each item can fail independently before ordinary final aggregation.
            # Public Task.failed must still carry a sanitized concrete error.
            error = _error()
        return self._complete(
            connection, row, status, result, error if status != "succeeded" else None
        )

    def finish(self, lease):
        with self._transaction(lease) as (connection, row):
            if row["kind"] != "diagnosis":
                raise ValueError("Ordinary tasks finalize together with their resource")
            return self._aggregate(connection, row)

    def _release_document(self, connection, row, status, profile_id=None):
        document = (
            connection.execute(
                select(db.documents).where(
                    db.documents.c.id == uid(row["input"]["document_id"]),
                    db.documents.c.session_id == row["session_id"],
                )
            )
            .mappings()
            .first()
        )
        if document is None:
            raise missing()
        if document["storage_key"]:
            self.repo._queue_file(connection, document["storage_key"])
        values = {"status": status}
        if profile_id is not None:
            values["profile_id"] = profile_id
        connection.execute(
            update(db.documents)
            .where(
                db.documents.c.id == document["id"], db.documents.c.session_id == row["session_id"]
            )
            .values(**values)
        )

    def _fail_locked(self, connection, row, error):
        if row["kind"] == "diagnosis":
            _, items = self._items(connection, row, lock=True)
            for item in items:
                if item["status"] not in TERMINAL_ITEMS:
                    self._update_item(
                        connection,
                        item,
                        status="score_only" if item["score_result"] is not None else "failed",
                        error=error,
                    )
            return self._aggregate(connection, row, error)
        if row["kind"] == "document_parse":
            self._release_document(connection, row, "failed")
        return self._complete(connection, row, "failed", error=error)

    def fail(self, lease, error):
        with self._transaction(lease) as (connection, row):
            return self._fail_locked(connection, row, _error(error))

    def commit_job(self, lease, content):
        with self._transaction(lease) as (connection, row):
            if row["kind"] != "job_parse":
                raise ValueError("Expected job_parse")
            job = self.repo._create_versioned(
                connection,
                self.repo.jobs,
                row["session_id"],
                content,
                raw_text=row["input"]["raw_text"],
                task_id=row["id"],
            )
            self._complete(
                connection,
                row,
                "succeeded",
                {
                    "resource_type": "job",
                    "resource_id": job.id,
                    "version": job.version,
                    "assistant_message": None,
                },
            )
            return job

    def commit_chat(self, lease, content, assistant_message):
        with self._transaction(lease) as (connection, row):
            if row["kind"] != "profile_chat":
                raise ValueError("Expected profile_chat")
            data, sid = row["input"], row["session_id"]
            profile = self.repo._append(
                connection,
                self.repo.profiles,
                data["profile"]["id"],
                sid,
                data["base_version"],
                content,
                created_by_task_id=row["id"],
            )
            if not isinstance(assistant_message, str) or not assistant_message.strip():
                raise ValueError("Expected a nonempty assistant message")
            for role, text in (("user", data["content"]), ("assistant", assistant_message)):
                connection.execute(
                    insert(db.messages).values(
                        id=data.get("message_id", row["id"]) if role == "user" else new_id(),
                        session_id=sid,
                        profile_id=profile.id,
                        task_id=row["id"],
                        role=role,
                        content=text,
                        created_at=self.repo.clock(),
                    )
                )
            self._complete(
                connection,
                row,
                "succeeded",
                {
                    "resource_type": "profile",
                    "resource_id": profile.id,
                    "version": profile.version,
                    "assistant_message": assistant_message,
                },
            )
            return profile

    def commit_document(self, lease, content, *, warnings=()):
        with self._transaction(lease) as (connection, row):
            if row["kind"] != "document_parse":
                raise ValueError("Expected document_parse")
            profile = self.repo._create_versioned(
                connection, self.repo.profiles, row["session_id"], content, task_id=row["id"]
            )
            self._release_document(connection, row, "parsed", profile.id)
            self._complete(
                connection,
                row,
                "succeeded",
                {
                    "resource_type": "profile",
                    "resource_id": profile.id,
                    "version": profile.version,
                    "assistant_message": None,
                    "warnings": list(warnings),
                },
            )
            return profile
