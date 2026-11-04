"""Focused follow-up runs against a disposable SQLite database and synthetic ports."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import func, select, update

from app.contracts import (
    DiagnosisCreate,
    DiagnosisFocus,
    Gap,
    MessageCreate,
    ProfileCreate,
    ReportContent,
    ResourceVersion,
)
from app.contracts.ports import StructuredResult
from app.intake import GatewayIntake
from app.intake.synthetic import (
    SYNTHETIC_JOB_RAW_TEXT,
    synthetic_job_content,
    synthetic_profile_content,
)
from app.platform.catalog import FakeModelCatalog
from app.platform.database_service import DatabasePlatform
from app.platform.errors import PlatformError
from app.platform.jobs.store import JobStore, LeaseLost
from app.platform.jobs.worker import Worker
from app.platform.repositories import schema as db
from app.platform.repositories.sqlite import SQLiteRepository, initialize_sqlite
from app.scoring import ScoringService

ANSWER = "我在课程项目中使用 SQL 清洗数据。"


class TargetGateway:
    is_fake = True

    def __init__(self, repo, catalog):
        self.repo, self.catalog, self.calls = repo, catalog, []

    async def generate_structured(self, name, prompt, schema, timeout, *, context):
        self.calls.append(deepcopy(prompt))
        content = deepcopy(prompt["profile_content"])
        if prompt["user_text"] == ANSWER:
            content["evidence"].append(
                {
                    "id": "e-answer",
                    "source_id": prompt["message_source_id"],
                    "source_type": "message",
                    "quote": ANSWER,
                    "locator": None,
                }
            )
            content["facts"][1].update(
                kind="project", application="applied", evidence_ids=["e-answer"]
            )
        return StructuredResult(
            {
                "assistant_message": "关于 SQL 的实际应用，你具体负责哪些数据清洗工作？",
                "profile_content": content,
            },
            self.catalog.resolve(context.model_id, "profile_chat", self.repo.now()),
        )


class Reporting:
    async def generate_report(self, profile, job, score, metadata, *, context):
        return ReportContent(
            summary="合成报告，无供应商调用。",
            gaps=[
                Gap(
                    requirement_id=a.requirement_id,
                    kind={
                        "unknown": "needs_evidence",
                        "partial": "partial_gap",
                        "unmet": "explicit_gap",
                    }[a.status],
                    description="核实对应事实",
                    evidence_ids=a.evidence_ids,
                )
                for a in score.assessments
                if a.status != "met"
            ],
            suggestions=[],
            actions=[],
        )


@pytest.fixture
def world(tmp_path):
    url = f"sqlite:///{tmp_path / 'followup.sqlite3'}"
    initialize_sqlite(url)
    repo = SQLiteRepository(url)
    sid = repo.create_session()[0].public.id
    catalog = FakeModelCatalog()
    platform = DatabasePlatform(repo, catalog, tmp_path)
    profile = repo.profile_create(
        sid, ProfileCreate(content=synthetic_profile_content()), uuid4().hex
    )
    profile = repo.confirm(repo.profiles, profile.id, sid, profile.version)
    job = repo.create_job(sid, SYNTHETIC_JOB_RAW_TEXT, synthetic_job_content())
    job = repo.confirm(repo.jobs, job.id, sid, job.version)
    store = JobStore(repo)
    gateway = TargetGateway(repo, catalog)
    worker = Worker(
        store,
        intake=GatewayIntake(gateway),
        scoring=ScoringService(),
        reporting=Reporting(),
        catalog=catalog,
        upload_dir=tmp_path,
        intake_factory=lambda source: GatewayIntake(gateway, source_id=source),
    )
    submitted = platform.diagnosis_create(
        sid,
        DiagnosisCreate(
            profile=ResourceVersion(id=profile.id, version=profile.version),
            jobs=[ResourceVersion(id=job.id, version=job.version)],
            model_id="demo-model-a",
        ),
        uuid4().hex,
    )
    asyncio.run(worker.run_once())
    diagnosis = repo.owned(repo.diagnoses, submitted.diagnosis_id, sid).value
    assert diagnosis.status == "succeeded"
    focus = DiagnosisFocus(
        diagnosis_id=diagnosis.id, item_id=diagnosis.items[0].id, requirement_id="r2"
    )
    yield SimpleNamespace(**locals())
    repo.close()


def request(world, *, questions=True, version=1, content="请围绕这条岗位要求提问。", focus=None):
    return MessageCreate(
        base_version=version,
        content=content,
        model_id="demo-model-a",
        diagnosis_focus=focus or world.focus,
        questions_only=questions,
    )


def task(world, task_id):
    return world.repo.owned(world.repo.tasks, task_id, world.sid).value


def count(world, table):
    with world.repo.engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(table))


def test_questions_and_noop_answers_preserve_confirmation_and_are_replayable(world):
    key = uuid4().hex
    body = request(world)
    started = world.platform.chat(world.sid, world.profile.id, body, key)
    assert world.platform.chat(world.sid, world.profile.id, body, key) == started
    asyncio.run(world.worker.run_once())
    result = task(world, started.task_id)
    assert result.status == "succeeded"
    assert result.result.diagnosis_focus == world.focus and result.result.questions_only
    assert result.result.version == 1
    current = world.repo.version(world.repo.profiles, world.profile.id, world.sid)
    assert current == world.profile
    assert [
        (m.role, m.content)
        for m in world.repo.owned(world.repo.profiles, current.id, world.sid).messages
    ] == [("assistant", result.result.assistant_message)]
    assert world.gateway.calls[-1]["user_text"] == ""
    assert "message_source_id" not in world.gateway.calls[-1]
    assert world.gateway.calls[-1]["diagnosis_focus"]["requirement"]["id"] == "r2"
    assert world.platform.chat(world.sid, current.id, body, key) == started
    with pytest.raises(PlatformError) as error:
        world.platform.chat(world.sid, current.id, request(world, content="different request"), key)
    assert error.value.info.code == "IDEMPOTENCY_CONFLICT"

    answered = world.platform.chat(
        world.sid,
        current.id,
        request(world, questions=False, content="暂时想不起来。"),
        uuid4().hex,
    )
    asyncio.run(world.worker.run_once())
    assert task(world, answered.task_id).result.version == 1
    assert count(world, db.profile_versions) == 1
    assert world.gateway.calls[-1]["history_user_messages"] == []
    messages = world.repo.owned(world.repo.profiles, current.id, world.sid).messages
    assert [m.role for m in messages] == ["assistant", "user", "assistant"]
    assert messages[1].content == "暂时想不起来。"


def test_answer_adds_confirmable_draft_and_reuses_frozen_job_after_confirmation(world):
    submitted = world.platform.chat(
        world.sid, world.profile.id, request(world, questions=False, content=ANSWER), uuid4().hex
    )
    asyncio.run(world.worker.run_once())
    assert task(world, submitted.task_id).status == "succeeded"
    current = world.repo.version(world.repo.profiles, world.profile.id, world.sid)
    assert current.version == 2 and not current.confirmed
    assert current.content.evidence[:-1] == world.profile.content.evidence
    messages = world.repo.owned(world.repo.profiles, current.id, world.sid).messages
    assert current.content.evidence[-1].source_id == messages[0].id
    body = DiagnosisCreate(
        profile=ResourceVersion(id=current.id, version=2),
        jobs=[world.diagnosis.items[0].job],
        model_id="demo-model-a",
    )
    with pytest.raises(PlatformError) as error:
        world.platform.diagnosis_create(world.sid, body, uuid4().hex)
    assert error.value.info.code == "UNCONFIRMED_VERSION"
    world.repo.confirm(world.repo.profiles, current.id, world.sid, 2)
    after = world.platform.diagnosis_create(world.sid, body, uuid4().hex)
    asyncio.run(world.worker.run_once())
    diagnosis = world.repo.owned(world.repo.diagnoses, after.diagnosis_id, world.sid).value
    assert diagnosis.items[0].job == world.diagnosis.items[0].job
    assert (
        next(
            a.status
            for a in diagnosis.items[0].score_result.assessments
            if a.requirement_id == "r2"
        )
        == "met"
    )
    assert (
        world.repo.owned(world.repo.diagnoses, world.diagnosis.id, world.sid).value
        == world.diagnosis
    )


@pytest.mark.parametrize(
    "invalid_target",
    ["foreign_session", "other_profile", "wrong_item", "met", "missing_requirement", "no_focus"],
)
def test_invalid_targets_cannot_create_task_or_idempotency_record(world, invalid_target):
    sid, profile_id, body = world.sid, world.profile.id, request(world)
    if invalid_target == "foreign_session":
        sid = world.repo.create_session()[0].public.id
        profile_id = world.repo.profile_create(
            sid, ProfileCreate(content=synthetic_profile_content()), uuid4().hex
        ).id
    elif invalid_target == "other_profile":
        profile_id = world.repo.profile_create(
            sid, ProfileCreate(content=synthetic_profile_content()), uuid4().hex
        ).id
    elif invalid_target == "wrong_item":
        body.diagnosis_focus.item_id = str(uuid4())
    elif invalid_target == "met":
        body.diagnosis_focus.requirement_id = "r1"
    elif invalid_target == "missing_requirement":
        body.diagnosis_focus.requirement_id = "not-in-job"
    else:
        body.diagnosis_focus = None
    before = (count(world, db.tasks), count(world, db.idempotency_keys))
    with pytest.raises(PlatformError):
        world.platform.chat(sid, profile_id, body, uuid4().hex)
    assert (count(world, db.tasks), count(world, db.idempotency_keys)) == before


def test_stale_noop_cannot_commit_and_new_base_can_use_old_diagnostic_target(world):
    submitted = world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
    edited = world.profile.content.model_copy(update={"overview": "用户主动编辑"}, deep=True)
    world.repo.append(world.repo.profiles, world.profile.id, world.sid, 1, content=edited)
    asyncio.run(world.worker.run_once())
    assert task(world, submitted.task_id).error.code == "VERSION_CONFLICT"
    assert count(world, db.messages) == 0
    fresh = world.platform.chat(world.sid, world.profile.id, request(world, version=2), uuid4().hex)
    asyncio.run(world.worker.run_once())
    assert task(world, fresh.task_id).result.version == 2
    assert world.gateway.calls[-1]["profile_content"]["overview"] == "用户主动编辑"
    assert world.gateway.calls[-1]["diagnosis_focus"]["profile"]["version"] == 1


def test_recovered_question_task_saves_one_assistant_and_no_new_version(world):
    submitted = world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
    first = world.store.claim()
    at = world.repo.clock() + timedelta(seconds=61)
    world.repo.clock = lambda: at
    second = world.store.claim()
    assert second.task_id == first.task_id and second.attempt == 2
    with pytest.raises(LeaseLost):
        world.store.commit_chat(first, world.profile.content, "stale")
    asyncio.run(world.worker.execute(second))
    assert task(world, submitted.task_id).status == "succeeded"
    assert count(world, db.messages) == 1 and count(world, db.profile_versions) == 1
    with pytest.raises(LeaseLost):
        world.store.commit_chat(second, world.profile.content, "duplicate")


def test_load_revalidates_frozen_target_and_revocation_fences_noop_commit(world):
    submitted = world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
    with world.repo.engine.begin() as connection:
        data = connection.scalar(select(db.tasks.c.input).where(db.tasks.c.id == submitted.task_id))
        data["diagnosis_focus_context"]["requirement"]["target"] = "tampered"
        connection.execute(
            update(db.tasks).where(db.tasks.c.id == submitted.task_id).values(input=data)
        )
    lease = world.store.claim()
    with pytest.raises(PlatformError):
        world.store.load(lease)
    world.repo.revoke(world.sid)
    with pytest.raises(LeaseLost):
        world.store.commit_chat(lease, world.profile.content, "must not reappear")
    assert count(world, db.messages) == 0


def test_question_only_rounds_count_toward_chat_limit_without_creating_user_sources(world):
    for _ in range(50):
        world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
        asyncio.run(world.worker.run_once())
    assert count(world, db.messages) == 50
    assert count(world, db.profile_versions) == 1
    with pytest.raises(PlatformError) as error:
        world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
    assert error.value.info.code == "VALIDATION_ERROR"
    messages = world.repo.owned(world.repo.profiles, world.profile.id, world.sid).messages
    assert all(message.role == "assistant" for message in messages)
