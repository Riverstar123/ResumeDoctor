"""API-01 orchestration using the shared ports and an explicit test repository."""

import asyncio
import hashlib
import io
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from html import escape

from pydantic import BaseModel, ValidationError

from app.contracts import (
    Diagnosis,
    DiagnosisAccepted,
    DiagnosisCreate,
    DiagnosisItem,
    ErrorInfo,
    Job,
    JobContent,
    JobCreate,
    JobUpdate,
    Message,
    MessageCreate,
    ModelMetadata,
    Profile,
    ProfileContent,
    ProfileCreate,
    ProfileUpdate,
    ReportContent,
    ResourceVersion,
    ScoreResult,
    Task,
    TaskAccepted,
    TaskResult,
)
from app.contracts.models import json_key
from app.contracts.ports import IntakePort, ReportingPort, ScoringPort, TaskContext
from app.platform.catalog import ModelCatalog
from app.platform.errors import PlatformError, conflict
from app.platform.fakes import FakeTaskExecutor
from app.platform.repositories import (
    IdempotencyRecord,
    InMemoryRepository,
    Owned,
    SessionRecord,
    Versioned,
    new_id,
)
from app.platform.validation import invalid, validate_job, validate_profile, validate_score

logger = logging.getLogger(__name__)
CAPABILITIES = {
    "document_parse": "profile_extract",
    "profile_chat": "profile_chat",
    "job_parse": "job_extract",
    "diagnosis": "diagnosis_report",
}
SAFE_TASK_CODES = {
    "NO_TEXT_LAYER",
    "DOCUMENT_PARSE_FAILED",
    "MODEL_TIMEOUT",
    "MODEL_OUTPUT_INVALID",
    "PROVIDER_UNAVAILABLE",
    "INPUT_TOO_LONG",
    "TASK_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "VERSION_CONFLICT",
    "VALIDATION_ERROR",
    "NO_SCORABLE_REQUIREMENTS",
    "INTERNAL_ERROR",
}


def task_error(exc: Exception) -> ErrorInfo:
    code = exc.info.code if isinstance(exc, PlatformError) else "INTERNAL_ERROR"
    if code not in SAFE_TASK_CODES:
        code = "INTERNAL_ERROR"
    # Never trust provider exception text, details, URLs or file paths.
    return ErrorInfo(code=code, message="任务处理失败；演示模式可检查配置后重试")


def port_dto(model, value):
    """Validate before any write, even if a port used model_construct or a dict."""
    try:
        data = (
            value.model_dump(mode="json", warnings=False) if isinstance(value, BaseModel) else value
        )
        return model.model_validate(data)
    except (ValidationError, TypeError, ValueError):
        raise PlatformError(422, "MODEL_OUTPUT_INVALID", "模块返回的结构不合法") from None


class Platform:
    def __init__(
        self,
        repository: InMemoryRepository,
        executor: FakeTaskExecutor,
        catalog: ModelCatalog,
        intake: IntakePort,
        scoring: ScoringPort,
        reporting: ReportingPort,
    ):
        self.repo, self.executor, self.catalog = repository, executor, catalog
        self.intake, self.scoring, self.reporting = intake, scoring, reporting
        self.futures: dict[str, tuple[str, asyncio.Task]] = {}
        self.profile_tasks: dict[str, str] = {}
        self.task_timeout_seconds = (
            300  # Test code can shorten this without changing the HTTP contract.
        )

    def prune(self) -> None:
        for sid, record in list(self.repo.sessions.items()):
            if record.expires_at <= self.repo.clock():
                self.revoke(sid)

    def revoke(self, sid: str) -> None:
        self.repo.revoke(sid)  # Invalidate first; every post-await commit checks active().
        for owner, future in list(self.futures.values()):
            if owner == sid:
                future.cancel()

    async def close(self) -> None:
        futures = [future for _, future in self.futures.values()]
        for future in futures:
            future.cancel()
        await asyncio.gather(*futures, return_exceptions=True)

    async def drain(self) -> None:
        await asyncio.gather(*(future for _, future in list(self.futures.values())))

    def write_limit(self, session: SessionRecord) -> None:
        now = self.repo.clock()
        session.writes = [t for t in session.writes if t > now - timedelta(minutes=1)]
        if len(session.writes) >= 20:
            raise PlatformError(429, "RATE_LIMITED", "写请求过于频繁，请稍后重试", retry_after=60)
        session.writes.append(now)

    def retry(self, sid: str, key: str, operation: str, body):
        self.repo.active(sid)
        digest = hashlib.sha256(json_key(body).encode("utf-8")).hexdigest()
        record = self.repo.keys.get((sid, key))
        if record and record.created_at <= self.repo.clock() - timedelta(hours=24):
            del self.repo.keys[sid, key]
            record = None
        if record:
            if record.operation != operation or record.digest != digest:
                raise PlatformError(409, "IDEMPOTENCY_CONFLICT", "幂等键已用于不同请求")
            return record.response.model_copy(deep=True), digest
        return None, digest

    def remember(self, sid: str, key: str, operation: str, digest: str, response):
        self.repo.keys[sid, key] = IdempotencyRecord(
            operation, digest, response.model_copy(deep=True), self.repo.clock()
        )
        return response

    def profile_create(self, sid: str, body: ProfileCreate, key: str) -> Profile:
        cached, digest = self.retry(sid, key, "profile_create", body)
        if cached:
            return cached
        validate_profile(body.content, self.repo.now()[:7])
        profile = Profile(
            id=new_id(),
            version=1,
            confirmed=False,
            content=body.content.model_copy(deep=True),
            created_at=self.repo.now(),
        )
        self.repo.profiles[profile.id] = Versioned(sid, [profile.model_copy(deep=True)])
        return self.remember(sid, key, "profile_create", digest, profile)

    def profile_update(self, sid: str, rid: str, body: ProfileUpdate) -> Profile:
        self.repo.owned(self.repo.profiles, rid, sid)
        validate_profile(body.content, self.repo.now()[:7])
        return self.repo.append(
            self.repo.profiles, rid, sid, body.base_version, content=body.content
        )

    def job_update(self, sid: str, rid: str, body: JobUpdate) -> Job:
        self.repo.owned(self.repo.jobs, rid, sid)
        validate_job(body.content, body.raw_text)
        return self.repo.append(
            self.repo.jobs,
            rid,
            sid,
            body.base_version,
            raw_text=body.raw_text,
            content=body.content,
        )

    def enqueue(
        self,
        sid: str,
        kind: str,
        model_id: str,
        work: Callable[[Task, ModelMetadata], Awaitable[TaskResult]],
        *,
        task_id: str | None = None,
        profile_id: str | None = None,
    ) -> Task:
        self.repo.active(sid)
        metadata = self.catalog.resolve(model_id, CAPABILITIES[kind], self.repo.now())
        if len(self.repo.active_tasks(sid)) >= 2:
            raise PlatformError(429, "RATE_LIMITED", "最多同时处理两个任务", retry_after=2)
        if profile_id and profile_id in self.profile_tasks:
            raise PlatformError(409, "PROFILE_BUSY", "该档案已有任务，请等待后重试")
        task = Task(
            id=task_id or new_id(),
            kind=kind,
            status="queued",
            model_id=model_id,
            result=None,
            error=None,
            created_at=self.repo.now(),
            updated_at=self.repo.now(),
        )
        self.repo.tasks[task.id] = Owned(sid, task)
        if profile_id:
            self.profile_tasks[profile_id] = task.id
        future = asyncio.create_task(self._run(sid, task, metadata, work, profile_id))
        self.futures[task.id] = (sid, future)
        return task

    async def _run(self, sid, task, metadata, work, profile_id):
        try:
            self.repo.active(sid)
            task.status, task.updated_at = "running", self.repo.now()

            async def execute():
                await self.executor.before(task.kind)
                self.repo.active(sid)
                # Check availability again but retain the enqueue-time mapping.
                self.catalog.resolve(task.model_id, CAPABILITIES[task.kind], self.repo.now())
                return await work(task, metadata)

            result = await asyncio.wait_for(execute(), timeout=self.task_timeout_seconds)
            self.repo.active(sid)
            task.result = result
            if task.status == "running":
                task.status = "succeeded"
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if sid in self.repo.sessions and task.id in self.repo.tasks:
                error = task_error(exc)
                if isinstance(exc, TimeoutError):
                    error = ErrorInfo(code="TASK_TIMEOUT", message="任务已超时")
                task.status, task.error = "failed", error
                for entry in self.repo.diagnoses.values():
                    diagnosis = entry.value
                    if entry.session_id == sid and diagnosis.task_id == task.id:
                        # Preserve completed scores if a later item times out.
                        for item in diagnosis.items:
                            if item.status in {"pending", "scoring", "reporting"}:
                                item.status = "score_only" if item.score_result else "failed"
                                item.error = error
                        if any(item.score_result for item in diagnosis.items):
                            task.status = "partial"
                            task.result = TaskResult(
                                resource_type="diagnosis",
                                resource_id=diagnosis.id,
                                version=None,
                                assistant_message=None,
                            )
                            task.error = None
                        diagnosis.status = task.status
                logger.warning("task_failed task_id=%s code=%s", task.id, error.code)
        finally:
            task.updated_at = self.repo.now()
            if profile_id and self.profile_tasks.get(profile_id) == task.id:
                self.profile_tasks.pop(profile_id, None)
            self.futures.pop(task.id, None)

    def chat(self, sid: str, rid: str, body: MessageCreate, key: str) -> TaskAccepted:
        rid = rid.lower()
        previous = self.repo.version(self.repo.profiles, rid, sid)
        cached, digest = self.retry(sid, key, f"chat:{rid}", body)
        if cached:
            return cached
        if previous.version != body.base_version:
            raise conflict()
        session = self.repo.active(sid)
        pending_chats = sum(t.kind == "profile_chat" for t in self.repo.active_tasks(sid))
        if session.user_rounds + pending_chats >= 50:
            raise PlatformError(422, "VALIDATION_ERROR", "用户消息已达到上限")
        record = self.repo.owned(self.repo.profiles, rid, sid)
        history = [m.model_copy(deep=True) for m in record.messages if m.role == "user"][-10:]

        async def work(task, metadata):
            output = await self.intake.advance_conversation(
                body.content, previous.content, history, context=TaskContext(task.model_id)
            )
            self.repo.active(sid)
            content = port_dto(ProfileContent, output.profile_content)
            messages = [
                port_dto(
                    Message,
                    {
                        "id": new_id(),
                        "role": "user",
                        "content": body.content,
                        "created_at": self.repo.now(),
                    },
                ),
                port_dto(
                    Message,
                    {
                        "id": new_id(),
                        "role": "assistant",
                        "content": output.assistant_message,
                        "created_at": self.repo.now(),
                    },
                ),
            ]
            validate_profile(content, self.repo.now()[:7])
            updated = self.repo.append(
                self.repo.profiles, rid, sid, body.base_version, content=content
            )
            record.messages.extend(messages)
            session.user_rounds += 1
            return TaskResult(
                resource_type="profile",
                resource_id=rid,
                version=updated.version,
                assistant_message=output.assistant_message,
            )

        task = self.enqueue(sid, "profile_chat", body.model_id, work, profile_id=rid)
        return self.remember(sid, key, f"chat:{rid}", digest, TaskAccepted(task_id=task.id))

    def job_create(self, sid: str, body: JobCreate, key: str) -> TaskAccepted:
        cached, digest = self.retry(sid, key, "job_create", body)
        if cached:
            return cached
        if not body.raw_text.strip():
            raise invalid()

        async def work(task, metadata):
            content = await self.intake.extract_job(
                body.raw_text, body.company_context, context=TaskContext(task.model_id)
            )
            self.repo.active(sid)
            content = port_dto(JobContent, content)
            validate_job(content, body.raw_text)
            job = Job(
                id=new_id(),
                version=1,
                confirmed=False,
                raw_text=body.raw_text,
                content=content,
                created_at=self.repo.now(),
            )
            self.repo.jobs[job.id] = Versioned(sid, [job])
            return TaskResult(
                resource_type="job", resource_id=job.id, version=1, assistant_message=None
            )

        task = self.enqueue(sid, "job_parse", body.model_id, work)
        return self.remember(sid, key, "job_create", digest, TaskAccepted(task_id=task.id))

    def document(
        self,
        sid: str,
        data: bytes,
        media_type: str,
        model_id: str,
        key: str,
        *,
        original_name: str = "upload",
    ):
        fingerprint = {"sha256": hashlib.sha256(data).hexdigest(), "model_id": model_id}
        cached, digest = self.retry(sid, key, "document", fingerprint)
        if cached:
            return cached

        async def work(task, metadata):
            with io.BytesIO(data) as handle:
                extracted = await self.intake.extract_document(handle, media_type)
            content = await self.intake.build_profile(
                extracted.text, "document", context=TaskContext(task.model_id)
            )
            self.repo.active(sid)
            content = port_dto(ProfileContent, content)
            validate_profile(content, self.repo.now()[:7])
            profile = Profile(
                id=new_id(), version=1, confirmed=False, content=content, created_at=self.repo.now()
            )
            self.repo.profiles[profile.id] = Versioned(sid, [profile])
            return TaskResult(
                resource_type="profile", resource_id=profile.id, version=1, assistant_message=None
            )

        task = self.enqueue(sid, "document_parse", model_id, work)
        return self.remember(sid, key, "document", digest, TaskAccepted(task_id=task.id))

    def diagnosis_create(self, sid: str, body: DiagnosisCreate, key: str) -> DiagnosisAccepted:
        # Verify every supplied reference before idempotency or business checks.
        profile = self.repo.version(self.repo.profiles, body.profile.id, sid, body.profile.version)
        jobs = [self.repo.version(self.repo.jobs, ref.id, sid, ref.version) for ref in body.jobs]
        cached, digest = self.retry(sid, key, "diagnosis", body)
        if cached:
            return cached
        if len({job.id for job in jobs}) != len(jobs):
            raise invalid()
        if not profile.confirmed or any(not job.confirmed for job in jobs):
            raise PlatformError(422, "UNCONFIRMED_VERSION", "请先确认档案和全部岗位版本")
        if any(not any(not r.ignored for r in job.content.requirements) for job in jobs):
            raise PlatformError(422, "NO_SCORABLE_REQUIREMENTS", "岗位没有可评分要求")
        diagnosis_id, task_id = new_id(), new_id()
        diagnosis = Diagnosis(
            id=diagnosis_id,
            task_id=task_id,
            status="queued",
            profile=ResourceVersion(id=profile.id, version=profile.version),
            model_id=body.model_id,
            items=[
                DiagnosisItem(
                    id=new_id(),
                    job=ResourceVersion(id=job.id, version=job.version),
                    status="pending",
                    score_result=None,
                    report=None,
                    error=None,
                    model_metadata=None,
                )
                for job in jobs
            ],
            created_at=self.repo.now(),
        )

        async def work(task, metadata):
            diagnosis.status = "running"
            for item, job in zip(diagnosis.items, jobs, strict=True):
                try:
                    item.status = "scoring"
                    await self.executor.before(f"scoring:{job.id}")
                    self.repo.active(sid)
                    assessments = self.scoring.assess_requirements(
                        profile.content.model_copy(deep=True),
                        job.content.model_copy(deep=True),
                        "matcher-v1",
                    )
                    score = port_dto(
                        ScoreResult, self.scoring.calculate_score(assessments, "coverage-v1")
                    )
                    validate_score(score, profile.content, job.content)
                    item.score_result, item.status = score, "reporting"
                    await self.executor.before(f"report:{job.id}")
                    report = await self.reporting.generate_report(
                        profile.model_copy(deep=True),
                        job.model_copy(deep=True),
                        score.model_copy(deep=True),
                        metadata.model_copy(deep=True),
                        context=TaskContext(task.model_id),
                    )
                    self.repo.active(sid)
                    report = port_dto(ReportContent, report)
                    requirement_ids = {r.id for r in job.content.requirements if not r.ignored}
                    evidence_ids = {e.id for e in profile.content.evidence}
                    states = {a.requirement_id: a.status for a in score.assessments}
                    if (
                        set(states) != requirement_ids
                        or len(states) != len(score.assessments)
                        or any(not set(a.evidence_ids) <= evidence_ids for a in score.assessments)
                        or any(
                            g.requirement_id not in states
                            or g.kind
                            != {
                                "unknown": "needs_evidence",
                                "partial": "partial_gap",
                                "unmet": "explicit_gap",
                            }.get(states[g.requirement_id])
                            or not set(g.evidence_ids) <= evidence_ids
                            for g in report.gaps
                        )
                        or any(
                            s.requirement_id not in requirement_ids
                            or not set(s.evidence_ids) <= evidence_ids
                            for s in report.suggestions
                        )
                        or any(a.requirement_id not in requirement_ids for a in report.actions)
                    ):
                        raise PlatformError(422, "MODEL_OUTPUT_INVALID", "报告引用不属于冻结快照")
                    item.report = report
                    item.model_metadata = metadata.model_copy(
                        update={"generated_at": self.repo.now()}
                    )
                    item.status = "succeeded"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.repo.active(sid)
                    item.error = task_error(exc)
                    item.status = "score_only" if item.score_result else "failed"
            status = (
                "succeeded"
                if all(i.status == "succeeded" for i in diagnosis.items)
                else ("partial" if any(i.score_result for i in diagnosis.items) else "failed")
            )
            task.status = diagnosis.status = status
            if status == "failed":
                task.error = ErrorInfo(code="INTERNAL_ERROR", message="所有岗位评分均失败")
                # failed may carry a readable diagnosis reference, but must have an error.
            return TaskResult(
                resource_type="diagnosis",
                resource_id=diagnosis_id,
                version=None,
                assistant_message=None,
            )

        task = self.enqueue(sid, "diagnosis", body.model_id, work, task_id=task_id)
        self.repo.diagnoses[diagnosis_id] = Owned(sid, diagnosis)
        response = DiagnosisAccepted(task_id=task.id, diagnosis_id=diagnosis_id)
        return self.remember(sid, key, "diagnosis", digest, response)

    def export(self, sid: str, rid: str) -> str:
        diagnosis = self.repo.owned(self.repo.diagnoses, rid, sid).value
        if diagnosis.status not in {"succeeded", "partial"}:
            raise PlatformError(409, "NOT_READY", "诊断尚无可导出的结果")
        header = (
            "# ResumeDoctor / 演示数据\n\n"
            f"档案：{diagnosis.profile.id} / v{diagnosis.profile.version}\n\n"
            f"模型选择：{escape(diagnosis.model_id)}\n\n状态：{diagnosis.status}\n\n"
        )
        return header + "\n".join(
            self.reporting.export_markdown(item.model_copy(deep=True)) for item in diagnosis.items
        )
