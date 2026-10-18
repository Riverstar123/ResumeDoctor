"""Process-local test repository. No persistence, shared worker or database claims.

Mutations do not await: within one event loop a validation/commit sequence is atomic.
API-01 must run with one process; DB-01 replaces this adapter with transactions.
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from app.contracts import Job, Message, Profile, Session, Task
from app.platform.errors import conflict, expired, missing


def new_id() -> str:
    return str(uuid4())


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class SessionRecord:
    public: Session
    token_hash: str
    expires_at: datetime
    writes: list[datetime] = field(default_factory=list)
    user_rounds: int = 0


@dataclass
class Versioned:
    session_id: str
    versions: list[Profile | Job]
    messages: list[Message] = field(default_factory=list)


@dataclass
class Owned:
    session_id: str
    value: Any


@dataclass
class IdempotencyRecord:
    operation: str
    digest: str
    response: Any
    created_at: datetime


class InMemoryRepository:
    is_fake = True

    def __init__(self, clock: Callable[[], datetime] | None = None):
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sessions: dict[str, SessionRecord] = {}
        self.tokens: dict[str, str] = {}
        self.profiles: dict[str, Versioned] = {}
        self.jobs: dict[str, Versioned] = {}
        self.tasks: dict[str, Owned] = {}
        self.diagnoses: dict[str, Owned] = {}
        self.keys: dict[tuple[str, str], IdempotencyRecord] = {}

    def now(self) -> str:
        return timestamp(self.clock())

    def create_session(self) -> tuple[SessionRecord, str]:
        token = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(token.encode()).hexdigest()
        expires_at = self.clock() + timedelta(days=7)
        public = Session(id=new_id(), expires_at=timestamp(expires_at))
        record = SessionRecord(public, hashed, expires_at)
        self.sessions[public.id] = record
        self.tokens[hashed] = public.id
        return record, token

    def authenticate(self, token: str | None) -> SessionRecord:
        if not token:
            raise expired()
        hashed = hashlib.sha256(token.encode()).hexdigest()
        sid = self.tokens.get(hashed)
        if sid is None:
            raise expired()
        return self.active(sid)

    def active(self, sid: str) -> SessionRecord:
        record = self.sessions.get(sid)
        if record is None:
            raise expired()
        if record.expires_at <= self.clock():
            self.revoke(sid)
            raise expired()
        return record

    def revoke(self, sid: str) -> None:
        record = self.sessions.pop(sid, None)
        if record:
            self.tokens.pop(record.token_hash, None)
        for table in (self.profiles, self.jobs, self.tasks, self.diagnoses):
            for rid in [rid for rid, entry in table.items() if entry.session_id == sid]:
                del table[rid]
        for key in [key for key in self.keys if key[0] == sid]:
            del self.keys[key]

    def owned(self, table: dict, rid: str, sid: str):
        self.active(sid)
        entry = table.get(rid.lower())
        if entry is None or entry.session_id != sid:
            raise missing()
        return entry

    def version(self, table: dict, rid: str, sid: str, version: int | None = None):
        record = self.owned(table, rid, sid)
        if version is None:
            return record.versions[-1].model_copy(deep=True)
        if version > len(record.versions):
            raise missing()
        return record.versions[version - 1].model_copy(deep=True)

    def append(self, table: dict, rid: str, sid: str, base: int, **changes):
        record = self.owned(table, rid, sid)
        latest = record.versions[-1]
        if latest.version != base:
            raise conflict()
        updated = latest.model_copy(
            deep=True,
            update={**changes, "version": base + 1, "confirmed": False, "created_at": self.now()},
        )
        record.versions.append(updated)
        return updated.model_copy(deep=True)

    def confirm(self, table: dict, rid: str, sid: str, version: int):
        record = self.owned(table, rid, sid)
        if record.versions[-1].version != version:
            raise conflict()
        record.versions[-1] = record.versions[-1].model_copy(update={"confirmed": True}, deep=True)
        return record.versions[-1].model_copy(deep=True)

    def active_tasks(self, sid: str) -> list[Task]:
        return [
            entry.value
            for entry in self.tasks.values()
            if entry.session_id == sid and entry.value.status in {"queued", "running"}
        ]
