"""DB-01 HTTP orchestration; queued work is persisted for the JOB-01 worker.

This adapter deliberately does not create in-process task futures. A successful
202 acknowledges the database transaction, not execution of an AI operation.
"""

import hashlib
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from threading import Lock

import anyio

from app.contracts import (
    DiagnosisAccepted,
    DiagnosisCreate,
    Job,
    JobCreate,
    JobUpdate,
    MessageCreate,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    TaskAccepted,
)
from app.platform.catalog import ModelCatalog
from app.platform.errors import PlatformError
from app.platform.fakes import FakeReporting
from app.platform.io import dispatch_io
from app.platform.repositories import SessionRecord
from app.platform.service import CAPABILITIES, Platform


class DatabasePlatform(Platform):
    """Preserve the API-01 route surface while delegating writes to transactions."""

    def __init__(self, repository, catalog: ModelCatalog, upload_dir: Path):
        self.repo = repository
        self.catalog = catalog
        self.upload_dir = upload_dir
        # Dedicated capacity avoids occupying Starlette's default worker budget.
        self._io_limiter = anyio.CapacityLimiter(8)
        # Same per-process HTTP write throttle as API-01. Resource/task limits
        # are additionally enforced inside the repository's SQL transaction.
        self._writes: dict[str, list[datetime]] = {}
        # Only the process-local HTTP throttle needs this lock. SQL transactions
        # and constraints still provide all resource/authorization consistency.
        self._writes_lock = Lock()
        # Export remains compatible with existing report JSON. No generation occurs.
        self.reporting = FakeReporting()

    async def run_io(self, function, *args, **kwargs):
        return await anyio.to_thread.run_sync(
            partial(function, *args, **kwargs),
            limiter=self._io_limiter,
            abandon_on_cancel=False,
        )

    def prune(self) -> None:
        self.repo.cleanup_expired()
        cutoff = self.repo.clock() - timedelta(minutes=1)
        with self._writes_lock:
            self._writes = {
                sid: recent
                for sid, entries in self._writes.items()
                if (recent := [entry for entry in entries if entry > cutoff])
            }

    def sweep(self) -> None:
        """Periodic lifecycle cleanup; file I/O never runs in the HTTP guard."""
        self.prune()
        self.repo.retry_file_cleanup(self.upload_dir)

    def revoke(self, sid: str) -> None:
        self.repo.revoke(sid)

    async def close(self) -> None:
        await dispatch_io(self, self.repo.close)

    def write_limit(self, session: SessionRecord) -> None:
        now = self.repo.clock()
        with self._writes_lock:
            entries = [
                entry
                for entry in self._writes.get(session.public.id, [])
                if entry > now - timedelta(minutes=1)
            ]
            if len(entries) >= 20:
                raise PlatformError(
                    429, "RATE_LIMITED", "写请求过于频繁，请稍后重试", retry_after=60
                )
            self._writes[session.public.id] = [*entries, now]

    def _snapshot(self, model_id: str, kind: str) -> dict:
        return self.catalog.resolve(model_id, CAPABILITIES[kind], self.repo.now()).model_dump(
            mode="json"
        )

    def profile_create(self, sid: str, body: ProfileCreate, key: str) -> Profile:
        return self.repo.profile_create(sid, body, key)

    def profile_update(self, sid: str, rid: str, body: ProfileUpdate) -> Profile:
        return self.repo.append(
            self.repo.profiles, rid, sid, body.base_version, content=body.content
        )

    def job_update(self, sid: str, rid: str, body: JobUpdate) -> Job:
        return self.repo.append(
            self.repo.jobs,
            rid,
            sid,
            body.base_version,
            raw_text=body.raw_text,
            content=body.content,
        )

    def chat(self, sid: str, rid: str, body: MessageCreate, key: str) -> TaskAccepted:
        rid = rid.lower()
        cached = self.repo.replay(sid, key, f"chat:{rid}", body)
        if cached is not None:
            return cached
        return self.repo.create_task(
            sid,
            "profile_chat",
            body.model_id,
            self._snapshot(body.model_id, "profile_chat"),
            {
                "profile": {"id": rid, "version": body.base_version},
                "base_version": body.base_version,
                "content": body.content,
            },
            key,
            f"chat:{rid}",
            body,
            profile_id=rid,
        )

    def job_create(self, sid: str, body: JobCreate, key: str) -> TaskAccepted:
        cached = self.repo.replay(sid, key, "job_create", body)
        if cached is not None:
            return cached
        return self.repo.create_task(
            sid,
            "job_parse",
            body.model_id,
            self._snapshot(body.model_id, "job_parse"),
            body.model_dump(mode="json"),
            key,
            "job_create",
            body,
        )

    def document(
        self,
        sid: str,
        data: bytes,
        media_type: str,
        model_id: str,
        key: str,
        *,
        original_name: str = "upload",
    ) -> TaskAccepted:
        fingerprint = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "model_id": model_id,
            "media_type": media_type,
        }
        cached = self.repo.replay(sid, key, "document", fingerprint)
        if cached is not None:
            return cached
        return self.repo.document_create(
            sid,
            data,
            media_type,
            model_id,
            key,
            self._snapshot(model_id, "document_parse"),
            self.upload_dir,
            original_name=original_name,
        )

    def diagnosis_create(self, sid: str, body: DiagnosisCreate, key: str) -> DiagnosisAccepted:
        cached = self.repo.replay(sid, key, "diagnosis", body)
        if cached is not None:
            return cached
        return self.repo.diagnosis_create(
            sid, body, key, self._snapshot(body.model_id, "diagnosis")
        )
