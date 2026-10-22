"""Independent durable worker orchestration; business ports never hold SQL locks."""

import asyncio
import io
import logging
import os
from pathlib import Path

from app.contracts import (
    JobContent,
    ModelMetadata,
    ProfileContent,
    ReportContent,
    ScoreResult,
)
from app.contracts.ports import TaskContext
from app.platform.errors import PlatformError
from app.platform.errors import task_error as background_error
from app.platform.service import CAPABILITIES, port_dto
from app.platform.validation import validate_score

from .store import JobStore, LeaseLost

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15


def validate_report(report, score, profile, job):
    report = port_dto(ReportContent, report)
    states = {a.requirement_id: a.status for a in score.assessments}
    requirements = {r.id for r in job.content.requirements if not r.ignored}
    evidence = {e.id for e in profile.content.evidence}
    if (
        set(states) != requirements
        or len(states) != len(score.assessments)
        or any(not set(a.evidence_ids) <= evidence for a in score.assessments)
        or any(
            g.requirement_id not in states
            or g.kind
            != {"unknown": "needs_evidence", "partial": "partial_gap", "unmet": "explicit_gap"}.get(
                states[g.requirement_id]
            )
            or not set(g.evidence_ids) <= evidence
            for g in report.gaps
        )
        or any(
            s.requirement_id not in requirements or not set(s.evidence_ids) <= evidence
            for s in report.suggestions
        )
        or any(a.requirement_id not in requirements for a in report.actions)
    ):
        raise PlatformError(422, "MODEL_OUTPUT_INVALID", "报告引用不属于冻结快照")
    return report


class Worker:
    def __init__(
        self,
        store,
        *,
        intake,
        scoring,
        reporting,
        catalog,
        upload_dir,
        heartbeat_seconds=HEARTBEAT_SECONDS,
    ):
        if not 0 < heartbeat_seconds <= HEARTBEAT_SECONDS:
            raise ValueError("heartbeat must be within the 15-second contract")
        self.store = store
        self.intake, self.scoring, self.reporting, self.catalog = (
            intake,
            scoring,
            reporting,
            catalog,
        )
        self.upload_dir = Path(upload_dir)
        self.heartbeat_seconds = heartbeat_seconds

    async def io(self, function, *args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)

    async def run_once(self):
        lease = await self.io(self.store.claim)
        if lease is None:
            return False
        await self.execute(lease)
        return True

    async def _heartbeat(self, lease):
        while True:
            remaining = (lease.deadline_at - self.store.repo.clock()).total_seconds()
            if remaining <= 0:
                raise TimeoutError()
            await asyncio.sleep(min(self.heartbeat_seconds, remaining))
            if not await self.io(self.store.heartbeat, lease):
                raise LeaseLost()

    async def execute(self, lease):
        """One claim only; recovery consumes a new DB claim, never a local retry."""
        work = asyncio.create_task(self._perform(lease))
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        try:
            remaining = max(0, (lease.deadline_at - self.store.repo.clock()).total_seconds())
            # The deadline must advance even if the heartbeat's own DB checkout
            # or row lock is blocked. It never depends on that thread returning.
            done, _ = await asyncio.wait(
                {work, heartbeat}, return_when=asyncio.FIRST_COMPLETED, timeout=remaining
            )
            if not done:
                raise TimeoutError()
            if heartbeat in done:
                await heartbeat
            await work
        except asyncio.CancelledError:
            # Process shutdown leaves the lease for recovery; no public cancelled status.
            raise
        except LeaseLost:
            pass
        except Exception as exc:
            # Stop external work before attempting any database failure write:
            # that write may itself be waiting on the lock that blocked heartbeat.
            work.cancel()
            heartbeat.cancel()
            await asyncio.gather(work, heartbeat, return_exceptions=True)
            error = background_error(exc)
            try:
                await self.io(self.store.fail, lease, error)
            except LeaseLost:
                pass
            logger.warning("job_failed task_id=%s code=%s", lease.task_id, error.code)
        finally:
            for task in (work, heartbeat):
                task.cancel()
            await asyncio.gather(work, heartbeat, return_exceptions=True)
            # A timed-out token cannot finalize itself; the fenced expiry path can.
            await self.io(self.store.reap)

    async def _perform(self, lease):
        context = TaskContext(lease.model_id)
        metadata = port_dto(ModelMetadata, lease.model_snapshot)
        current = self.catalog.resolve(
            lease.model_id, CAPABILITIES[lease.kind], self.store.repo.now()
        )
        fields = ("model_id", "provider", "model", "prompt_version", "gateway_config_version")
        if any(getattr(current, key) != getattr(metadata, key) for key in fields):
            raise PlatformError(422, "MODEL_UNAVAILABLE", "模型映射已变化，请重新创建任务")
        data = await self.io(self.store.load, lease)
        if lease.kind == "job_parse":
            content = await self.intake.extract_job(
                lease.input["raw_text"], lease.input["company_context"], context=context
            )
            await self.io(self.store.commit_job, lease, port_dto(JobContent, content))
        elif lease.kind == "profile_chat":
            output = await self.intake.advance_conversation(
                lease.input["content"],
                data.profile.content.model_copy(deep=True),
                data.history[-10:],
                context=context,
            )
            await self.io(
                self.store.commit_chat,
                lease,
                port_dto(ProfileContent, output.profile_content),
                output.assistant_message,
            )
        elif lease.kind == "document_parse":
            # The filesystem thread owns and closes its descriptor, even if the
            # awaiting task is cancelled before the thread returns. The borrowed
            # in-memory stream cannot keep an original file open on Windows.
            handle = io.BytesIO(await self.io(self._read_document, data.document))
            try:
                extracted = await self.intake.extract_document(handle, data.document["media_type"])
            finally:
                handle.close()
            content = await self.intake.build_profile(extracted.text, "document", context=context)
            await self.io(self.store.commit_document, lease, port_dto(ProfileContent, content))
        elif lease.kind == "diagnosis":
            for item, job in zip(data.diagnosis.items, data.jobs, strict=True):
                if item.status in {"succeeded", "score_only", "failed"}:
                    continue
                try:
                    score = item.score_result
                    if score is None:
                        await self.io(self.store.start_item, lease, item.id)
                        score = await self.io(self._score, data.profile, job)
                        await self.io(self.store.save_score, lease, item.id, score)
                    report = await self.reporting.generate_report(
                        data.profile.model_copy(deep=True),
                        job.model_copy(deep=True),
                        score.model_copy(deep=True),
                        metadata.model_copy(deep=True),
                        context=context,
                    )
                    report = validate_report(report, score, data.profile, job)
                    await self.io(
                        self.store.finish_item,
                        lease,
                        item.id,
                        report=report,
                        metadata=metadata.model_copy(
                            update={"generated_at": self.store.repo.now()}
                        ),
                    )
                except LeaseLost:
                    raise
                except Exception as exc:
                    await self.io(
                        self.store.finish_item, lease, item.id, error=background_error(exc)
                    )
            await self.io(self.store.finish, lease)
        else:
            raise PlatformError(422, "VALIDATION_ERROR", "未知任务类型")

    def _score(self, profile, job):
        assessments = self.scoring.assess_requirements(
            profile.content.model_copy(deep=True), job.content.model_copy(deep=True), "matcher-v1"
        )
        score = port_dto(ScoreResult, self.scoring.calculate_score(assessments, "coverage-v1"))
        validate_score(score, profile.content, job.content)
        return score

    def _read_document(self, document):
        from app.platform.repositories.postgres import uid

        key = document["storage_key"]
        if not key or uid(key) != key:
            raise PlatformError(422, "DOCUMENT_PARSE_FAILED", "原件不可用")
        descriptor = os.open(self.upload_dir / key, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise PlatformError(413, "FILE_TOO_LARGE", "原件超过10 MiB")
        return data


def create_worker(settings=None, *, repository=None, directory=None, gateway=None, **ports):
    """Use INT-01 synthetic ports, real M4 and E's fake gateway; never a provider."""
    from app.intake import SyntheticIntake
    from app.llm import FakeModelDirectory, FakeModelGateway
    from app.platform.integration import GatewayCatalog, GatewayReporting
    from app.platform.repositories import PostgreSQLRepository
    from app.scoring import ScoringService
    from app.settings import load_settings

    settings = settings if settings is not None else load_settings()
    if settings.llm_mode != "fake":
        raise ValueError("JOB-01 assembly requires fake mode; real integration belongs to INT-02")
    repository = (
        repository
        if repository is not None
        else PostgreSQLRepository(settings.database_url.get_secret_value())
    )
    directory = directory if directory is not None else FakeModelDirectory()
    gateway = gateway if gateway is not None else FakeModelGateway(directory)
    return Worker(
        JobStore(repository),
        intake=ports.pop("intake", SyntheticIntake()),
        scoring=ports.pop("scoring", ScoringService()),
        reporting=ports.pop("reporting", GatewayReporting(gateway)),
        catalog=ports.pop("catalog", GatewayCatalog(directory)),
        upload_dir=settings.upload_dir,
        **ports,
    )
