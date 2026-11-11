"""Focused follow-up runs against a disposable SQLite database and synthetic ports."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import func, select, update

from app.contracts import (
    DiagnosisCreate,
    DiagnosisFocus,
    Evidence,
    Fact,
    Gap,
    JobContent,
    MessageCreate,
    ProfileContent,
    ProfileCreate,
    ReportContent,
    Requirement,
    RequirementVerification,
    ResourceVersion,
    VerifiedRequirement,
)
from app.contracts.ports import StructuredResult
from app.intake import GatewayIntake
from app.intake.synthetic import (
    SYNTHETIC_JOB_RAW_TEXT,
    synthetic_job_content,
    synthetic_profile_content,
)
from app.llm.schemas import ChatOutput
from app.platform.catalog import FakeModelCatalog
from app.platform.database_service import DatabasePlatform
from app.platform.errors import PlatformError
from app.platform.jobs.store import JobStore, LeaseLost
from app.platform.jobs.worker import Worker
from app.platform.repositories import schema as db
from app.platform.repositories.sqlite import SQLiteRepository, initialize_sqlite
from app.scoring import ScoringService
from app.scoring.calculator import coverage_percentage

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
    assert (
        world.gateway.calls[-1]["history_assistant_messages"][0]["content"]
        == result.result.assistant_message
    )
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


def test_manual_review_counts_only_explicitly_verified_evidence_for_the_same_job(world):
    repo, sid, platform = world.repo, world.sid, world.platform
    content = synthetic_profile_content()
    content.facts[1].kind = "project"
    content.facts[1].application = "applied"
    content.evidence[1].quote = "使用 SQL 汇总课程项目的订单数据。"
    profile = repo.profile_create(sid, ProfileCreate(content=content), uuid4().hex)
    repo.confirm(repo.profiles, profile.id, sid, 1)
    job_content = synthetic_job_content()
    job_content.requirements[2] = job_content.requirements[2].model_copy(
        update={
            "quote": "有 A/B 实验实践经验者优先。",
            "category": "experience",
            "operator": "manual_review",
            "target": "A/B 实验",
        }
    )
    job_content.requirements[3].importance = "must"
    raw_text = "\n".join(requirement.quote for requirement in job_content.requirements)
    job = repo.create_job(sid, raw_text, job_content)
    repo.confirm(repo.jobs, job.id, sid, job.version)
    request = DiagnosisCreate(
        profile=ResourceVersion(id=profile.id, version=1),
        jobs=[ResourceVersion(id=job.id, version=job.version)],
    )

    def completed(accepted):
        asyncio.run(world.worker.run_once())
        result = repo.owned(repo.diagnoses, accepted.diagnosis_id, sid).value
        assert result.status == "succeeded"
        return result

    baseline = completed(platform.diagnosis_create(sid, request, uuid4().hex))
    before = baseline.items[0].score_result
    assert coverage_percentage(before.assessments) == 85.7

    evidence = Evidence(
        id="e-ab",
        source_type="manual",
        source_id="manual-ab",
        quote="参与优惠券文案的 A/B 实验，按用户随机分组，负责汇总两组下单转化率。",
        locator=None,
    )
    content.evidence.append(evidence)
    content.facts.append(
        Fact(
            id="f-ab",
            kind="experience",
            label="A/B 实验",
            value=None,
            polarity="positive",
            application="applied",
            start_month=None,
            end_month=None,
            completed=None,
            evidence_ids=[evidence.id],
        )
    )
    repo.append(repo.profiles, profile.id, sid, 1, content=content)
    request.profile.version = 2
    verified = request.model_copy(deep=True)
    verified.requirement_verification = RequirementVerification(
        focus=DiagnosisFocus(
            diagnosis_id=baseline.id, item_id=baseline.items[0].id, requirement_id="r3"
        ),
        evidence_id=evidence.id,
    )
    with pytest.raises(PlatformError) as unconfirmed:
        platform.diagnosis_create(sid, verified, uuid4().hex)
    assert unconfirmed.value.info.code == "UNCONFIRMED_VERSION"
    repo.confirm(repo.profiles, profile.id, sid, 2)
    with pytest.raises(PlatformError) as invalid_evidence:
        invalid_request = verified.model_copy(deep=True)
        invalid_request.requirement_verification.evidence_id = "missing"
        platform.diagnosis_create(sid, invalid_request, uuid4().hex)
    assert invalid_evidence.value.info.code == "VALIDATION_ERROR"
    invalid_request = verified.model_copy(deep=True)
    invalid_request.requirement_verification.fact_id = "f1"
    with pytest.raises(PlatformError) as invalid_fact:
        platform.diagnosis_create(sid, invalid_request, uuid4().hex)
    assert invalid_fact.value.info.code == "VALIDATION_ERROR"
    with pytest.raises(PlatformError):
        invalid_request = verified.model_copy(update={"jobs": [world.diagnosis.items[0].job]})
        platform.diagnosis_create(sid, invalid_request, uuid4().hex)

    unverified_key = uuid4().hex
    unverified_request = platform.diagnosis_create(sid, request, unverified_key)
    unverified = completed(unverified_request)
    assert platform.diagnosis_create(sid, request, unverified_key) == unverified_request
    assert coverage_percentage(unverified.items[0].score_result.assessments) == 85.7
    key = uuid4().hex
    accepted = platform.diagnosis_create(sid, verified, key)
    result = completed(accepted)
    assert result.requirement_verification == verified.requirement_verification
    after = result.items[0]
    assert platform.diagnosis_create(sid, verified, key) == accepted
    assert after.job == baseline.items[0].job
    assert coverage_percentage(after.score_result.assessments) == 100.0
    row = next(a for a in after.score_result.assessments if a.requirement_id == "r3")
    assert row.status == "met" and row.counted_in_score and row.unknown_reason is None
    assert row.evidence_ids == [evidence.id] and "用户已核验" in row.reason
    assert all(g.requirement_id != "r3" for g in after.report.gaps)
    assert repo.owned(repo.diagnoses, baseline.id, sid).value == baseline
    replay = request.model_copy(
        update={"requirement_verification": result.requirement_verification}
    )
    repeated = completed(platform.diagnosis_create(sid, replay, uuid4().hex))
    assert repeated.items[0].score_result == after.score_result
    assert world.gateway.calls == []


def manual_requirement(identifier, label):
    return Requirement(
        id=identifier,
        quote=f"有{label}经验者优先。",
        category="experience",
        importance="preferred",
        operator="manual_review",
        target=label,
        ignored=False,
        ignore_reason=None,
        subject=None,
    )


def completed_diagnosis(world, body):
    accepted = world.platform.diagnosis_create(world.sid, body, uuid4().hex)
    asyncio.run(world.worker.run_once())
    result = world.repo.owned(world.repo.diagnoses, accepted.diagnosis_id, world.sid).value
    assert result.status == "succeeded"
    return result


def manual_review_baseline(world, requirements):
    # Keep one scored condition so the baseline exercises the normal coverage calculation.
    requirements = [world.job.content.requirements[0], *requirements]
    content = world.job.content.model_copy(update={"requirements": requirements})
    raw = "\n".join(requirement.quote for requirement in requirements)
    job = world.repo.create_job(world.sid, raw, content)
    world.repo.confirm(world.repo.jobs, job.id, world.sid, job.version)
    return completed_diagnosis(
        world,
        DiagnosisCreate(
            profile=world.diagnosis.profile,
            jobs=[ResourceVersion(id=job.id, version=job.version)],
        ),
    )


def add_verified_example(content, identifier, label, quote):
    evidence_id = f"e-{identifier}"
    content.evidence.append(
        Evidence(
            id=evidence_id, source_type="manual", source_id=identifier, quote=quote, locator=None
        )
    )
    content.facts.append(
        Fact(
            id=f"f-{identifier}",
            kind="experience",
            label=label,
            value=None,
            polarity="positive",
            application="applied",
            start_month=None,
            end_month=None,
            completed=None,
            evidence_ids=[evidence_id],
        )
    )


@pytest.mark.parametrize(
    "case",
    [
        "clear",
        "ambiguous",
        "wrong_source",
        "edited",
        "observer_match",
        "denial_match",
        "clipped",
        "redacted_full",
        "redacted_contact_only",
        "redacted_email_sentence",
        "redacted_phone_sentence",
        "redacted_clipped_denial",
        "redacted_phone_denial",
    ],
)
def test_showcase_ab_experiment_scores_once_the_ai_draft_is_confirmed(world, monkeypatch, case):
    # Original synthetic showcase resume, JD and follow-up answer.
    education = "教育：2022年9月至2026年6月，财务管理专业，已取得本科学历。"
    internship = (
        "实习：2026年3月至2026年6月，虚构公司澄禾零售，经营分析实习生。"
        "用 SQL 汇总订单数据，用 Python pandas 清洗订单记录，使用 Excel 数据透视表按门店汇总销售与退货，"
        "制作每周经营报表，供运营团队复盘。"
    )
    supplement = (
        "在澄禾零售参与优惠券文案的 A/B 实验。将用户随机分成两组，"
        "负责用 SQL 汇总两组的下单转化率，并向运营团队汇报。"
    )
    observed = "在澄禾零售看过同事汇报的 A/B 实验结果。"
    denied = "我仅查看了同事 A/B 实验的结果，没有参与或执行任何实验。"
    email = "synthetic@example.test"
    phone = "+1 (202) 555-0143"
    contact = f"\n邮箱：{email}。"
    answer = {
        "redacted_full": supplement + contact,
        "redacted_contact_only": supplement + contact,
        "redacted_email_sentence": f"{supplement}我的邮箱是 {email}。",
        "redacted_phone_sentence": f"{supplement}我的手机号码是 {phone}。",
        "redacted_clipped_denial": observed + contact + "\n我没有参与设计或执行实验。",
        "redacted_phone_denial": f"{observed}我的手机号码是 {phone}，但我没有参与设计或执行实验。",
        "ambiguous": observed,
        "observer_match": observed,
        "denial_match": denied,
        "clipped": observed + "我没有参与设计或执行实验。",
    }.get(case, supplement)
    redacted_short = {
        "redacted_contact_only",
        "redacted_email_sentence",
        "redacted_phone_sentence",
    }
    clipped = {"clipped", "redacted_clipped_denial", "redacted_phone_denial"}
    title = "经营数据分析实习生（虚构岗位）"
    jd = (
        f"岗位：{title}\n要求：本科及以上学历。\n能用 SQL 汇总业务数据。\n"
        "能用 Python pandas 清洗数据。\n有 A/B 实验实践经验者优先。"
    )
    content = ProfileContent(
        overview="林予安｜求职演示合成简历",
        as_of_month="2026-11",
        facts=[],
        evidence=[],
    )
    add_verified_example(content, "degree", "财务管理", education)
    content.facts[0] = content.facts[0].model_copy(
        update={"kind": "education", "value": "bachelor", "completed": True}
    )
    add_verified_example(content, "sql", "SQL", internship)
    add_verified_example(content, "pandas", "Python pandas", internship)
    if case == "observer_match":
        add_verified_example(content, "other-ab", "优惠券文案实验", supplement)
    profile = world.repo.profile_create(world.sid, ProfileCreate(content=content), uuid4().hex)
    world.repo.confirm(world.repo.profiles, profile.id, world.sid, profile.version)
    fixture = Path(__file__).resolve().parents[3] / "docs/examples/job.json"
    job_content = json.loads(fixture.read_text(encoding="utf-8"))["content"]
    job_content["title"] = title
    _, degree, sql, pandas, ab_test = jd.splitlines()
    rows = job_content["requirements"]
    rows[0].update(quote=pandas, target="Python pandas")
    rows[1].update(quote=sql)
    rows[2].update(
        quote=ab_test, target="A/B 实验", category="experience", operator="manual_review"
    )
    rows[3].update(quote=degree.removeprefix("要求："), importance="must")
    job = world.repo.create_job(world.sid, jd, JobContent.model_validate(job_content))
    world.repo.confirm(world.repo.jobs, job.id, world.sid, job.version)
    baseline = completed_diagnosis(
        world,
        DiagnosisCreate(
            profile=ResourceVersion(id=profile.id, version=profile.version),
            jobs=[ResourceVersion(id=job.id, version=job.version)],
        ),
    )
    item = baseline.items[0]
    assert coverage_percentage(item.score_result.assessments) == 85.7
    focus = DiagnosisFocus(diagnosis_id=baseline.id, item_id=item.id, requirement_id="r3")

    async def organize(name, prompt, schema, timeout, *, context):
        world.gateway.calls.append(deepcopy(prompt))
        assert name == "profile_chat"
        assert prompt["diagnosis_focus"]["requirement"]["quote"] == ab_test
        draft = ProfileContent.model_validate(prompt["profile_content"])
        label = (
            "查看同事的实验结果"
            if case in {"observer_match", "denial_match"} or case in clipped
            else "优惠券文案实验"
        )
        if case.startswith("redacted_"):
            assert email not in prompt["user_text"] and phone not in prompt["user_text"]
        if case in clipped:
            quote = observed
        elif case in redacted_short:
            quote = supplement
        else:
            quote = prompt["user_text"] if case == "redacted_full" else answer
        add_verified_example(draft, "ab", label, quote)
        draft.evidence[-1] = draft.evidence[-1].model_copy(
            update={"source_type": "message", "source_id": prompt["message_source_id"]}
        )
        match = {"fact_id": "f-ab", "evidence_id": "e-ab"}
        if case == "ambiguous":
            match = None
        if case == "wrong_source":
            match = {"fact_id": "f-sql", "evidence_id": "e-sql"}
        response = ChatOutput.model_validate(
            {
                "assistant_message": "请核对补充经历。",
                "profile_content": draft,
                "followup_match": match,
            }
        )
        return StructuredResult(
            response.model_dump(mode="json"),
            world.catalog.resolve(context.model_id, name, world.repo.now()),
        )

    monkeypatch.setattr(world.gateway, "generate_structured", organize)
    submitted = world.platform.chat(
        world.sid,
        profile.id,
        request(world, questions=False, version=profile.version, content=answer, focus=focus),
        uuid4().hex,
    )
    asyncio.run(world.worker.run_once())
    result = task(world, submitted.task_id)
    assert result.status == "succeeded"
    assert len(world.gateway.calls) == 1
    adopt = case in {"clear", "redacted_full"} or case in redacted_short
    has_proposal = adopt or case in {"edited", "observer_match", "denial_match"}
    assert (result.result.followup_match is not None) == has_proposal
    current = world.repo.version(world.repo.profiles, profile.id, world.sid)
    assert (current.followup_assessment is not None) == has_proposal
    if case == "edited":
        current = world.repo.append(
            world.repo.profiles,
            profile.id,
            world.sid,
            current.version,
            content=current.content.model_copy(update={"overview": "手动修改后的档案"}),
        )
    rerun = DiagnosisCreate(
        profile=ResourceVersion(id=profile.id, version=current.version),
        jobs=[item.job],
        requirement_verification=RequirementVerification(focus=focus, evidence_id=None),
    )
    with pytest.raises(PlatformError) as error:
        world.platform.diagnosis_create(world.sid, rerun, uuid4().hex)
    assert error.value.info.code == "UNCONFIRMED_VERSION"
    world.repo.confirm(world.repo.profiles, profile.id, world.sid, current.version)
    reopened = world.repo.version(world.repo.profiles, profile.id, world.sid)
    assert reopened.confirmed
    assert (reopened.followup_assessment is not None) == (has_proposal and case != "edited")
    # Old clients and users who decline send null and keep the condition pending,
    # including when the model mistakenly endorsed observing or explicitly denying an experiment.
    legacy = completed_diagnosis(world, rerun)
    assert coverage_percentage(legacy.items[0].score_result.assessments) == 85.7
    assert legacy.verified_requirements == []
    if case == "observer_match":
        manual = rerun.model_copy(deep=True)
        manual.requirement_verification.evidence_id = "e-other-ab"
        manual.requirement_verification.fact_id = "f-other-ab"
        manual_report = completed_diagnosis(world, manual)
        assert coverage_percentage(manual_report.items[0].score_result.assessments) == 100.0
        assert manual_report.verified_requirements == [
            VerifiedRequirement(requirement_id="r3", evidence_id="e-other-ab", fact_id="f-other-ab")
        ]
    if adopt:
        rerun.requirement_verification.use_ai_match = True
    if case == "edited" or case in clipped:
        rejected = rerun.model_copy(deep=True)
        rejected.requirement_verification.use_ai_match = True
        with pytest.raises(PlatformError) as error:
            world.platform.diagnosis_create(world.sid, rejected, uuid4().hex)
        assert error.value.info.code == "VALIDATION_ERROR"
    after = completed_diagnosis(world, rerun) if adopt else legacy
    score = after.items[0].score_result
    assessment = next(row for row in score.assessments if row.requirement_id == "r3")
    assert after.items[0].job == item.job
    assert len(world.gateway.calls) == 1
    if adopt:
        assert coverage_percentage(score.assessments) == 100.0
        assert (assessment.status, assessment.coefficient, assessment.evidence_ids) == (
            "met",
            1,
            ["e-ab"],
        )
        assert current.content.evidence[-1].quote == answer
        assert after.verified_requirements == [
            VerifiedRequirement(
                requirement_id="r3", evidence_id="e-ab", fact_id="f-ab", model_assessed=True
            )
        ]
    else:
        assert coverage_percentage(score.assessments) == 85.7
        assert assessment.unknown_reason == "manual_review"
        assert after.verified_requirements == []


def followup_rerun(world, baseline, content, requirement_id, evidence_id):
    profile_id = baseline.profile.id
    edited = world.repo.append(
        world.repo.profiles, profile_id, world.sid, baseline.profile.version, content=content
    )
    world.repo.confirm(world.repo.profiles, profile_id, world.sid, edited.version)
    return DiagnosisCreate(
        profile=ResourceVersion(id=profile_id, version=edited.version),
        jobs=[baseline.items[0].job],
        requirement_verification=RequirementVerification(
            focus=DiagnosisFocus(
                diagnosis_id=baseline.id,
                item_id=baseline.items[0].id,
                requirement_id=requirement_id,
            ),
            evidence_id=evidence_id,
        ),
    )


def test_mixed_condition_cannot_be_verified_with_evidence_for_the_manual_part(world):
    mixed = Requirement.model_validate(
        {
            **manual_requirement("r-mixed", "A/B 实验").model_dump(),
            "quote": "必须掌握 Bloomberg，且有 A/B 实验经验。",
            "operator": "criteria",
            "condition": {
                "any_of": [
                    {
                        "scope": "profile",
                        "all_of": [
                            {
                                "field": "skill",
                                "comparison": "eq",
                                "value": "Bloomberg",
                                "quote": "掌握 Bloomberg",
                            },
                            {
                                "field": "manual",
                                "comparison": "eq",
                                "value": "A/B 实验",
                                "quote": "有 A/B 实验经验",
                            },
                        ],
                    }
                ]
            },
        }
    )
    baseline = manual_review_baseline(world, [mixed])
    content = world.profile.content.model_copy(deep=True)
    add_verified_example(content, "ab", "A/B 实验", "参与 A/B 实验，随机分组并汇总转化率。")
    body = followup_rerun(world, baseline, content, mixed.id, "e-ab")
    with pytest.raises(PlatformError) as error:
        world.platform.diagnosis_create(world.sid, body, uuid4().hex)
    assert error.value.info.code == "VALIDATION_ERROR"
    body.requirement_verification.evidence_id = None
    rerun = completed_diagnosis(world, body)
    row = next(a for a in rerun.items[0].score_result.assessments if a.requirement_id == mixed.id)
    assert row.status == "unknown" and row.coefficient == 0
    assert "Bloomberg" in row.reason
    assert rerun.verified_requirements == []


@pytest.mark.parametrize(
    "old_evidence",
    [
        "unchanged",
        "edited",
        "fact_edited",
        "removed",
        "negative",
        "contradicted",
        "different_label",
        "jd_label_correction",
        "unrelated_negative",
        "shared_exact",
        "shared_alternate",
        "shared_alternate_correction",
    ],
)
def test_later_verification_carries_only_still_valid_evidence(world, old_evidence):
    ab, valuation = manual_requirement("r-ab", "A/B 实验"), manual_requirement("r-val", "估值建模")
    baseline = manual_review_baseline(world, [ab, valuation])
    content = world.profile.content.model_copy(deep=True)
    alternate = old_evidence in {
        "different_label",
        "jd_label_correction",
        "shared_alternate",
        "shared_alternate_correction",
    }
    shared = old_evidence.startswith("shared_")
    fact_label = "优惠券文案实验" if alternate else ab.target
    quote = "参与优惠券文案的 A/B 实验，随机分组并汇总转化率。"
    if shared:
        quote += "也负责预算编制。"
    add_verified_example(content, "ab", fact_label, quote)
    if shared:
        content.facts.append(
            content.facts[-1].model_copy(update={"id": "f-budget", "label": "预算编制"})
        )
    first_request = followup_rerun(world, baseline, content, ab.id, "e-ab")
    if shared and alternate:
        with pytest.raises(PlatformError) as ambiguous:
            world.platform.diagnosis_create(world.sid, first_request, uuid4().hex)
        assert ambiguous.value.info.code == "VALIDATION_ERROR"
        first_request.requirement_verification.fact_id = "f-ab"
    first = completed_diagnosis(world, first_request)
    ab_record = VerifiedRequirement(requirement_id=ab.id, evidence_id="e-ab", fact_id="f-ab")
    assert first.verified_requirements == [ab_record]

    if old_evidence == "edited":
        content.evidence[-1].quote = "参加过实验设计课程。"
    elif old_evidence == "fact_edited":
        content.facts[-1].value = "仅了解实验原理"
    elif old_evidence == "removed":
        content.evidence.pop()
        content.facts.pop()
    elif old_evidence == "negative":
        content.facts[-1].polarity = "negative"
    elif shared or old_evidence in {
        "contradicted",
        "different_label",
        "jd_label_correction",
        "unrelated_negative",
    }:
        label = {
            "unrelated_negative": "预算编制",
            "shared_exact": "预算编制",
            "shared_alternate": "预算编制",
            "jd_label_correction": ab.target,
        }.get(old_evidence, fact_label.lower())
        add_verified_example(content, "correction", label, f"更正前一条记录：我没有参与过{label}。")
        content.facts[-1].polarity = "negative"
    add_verified_example(content, "val", valuation.target, "在课程项目中建立现金流折现估值模型。")
    second_request = followup_rerun(world, first, content, valuation.id, "e-val")
    if old_evidence == "unchanged":
        carry_only = second_request.model_copy(deep=True)
        carry_only.requirement_verification.evidence_id = None
        assert completed_diagnosis(world, carry_only).verified_requirements == [ab_record]
    second = completed_diagnosis(world, second_request)
    retained = old_evidence in {
        "unchanged",
        "unrelated_negative",
        "shared_exact",
        "shared_alternate",
    }
    assert second.verified_requirements == [
        *([ab_record] if retained else []),
        VerifiedRequirement(requirement_id=valuation.id, evidence_id="e-val", fact_id="f-val"),
    ]
    rows = {a.requirement_id: a for a in second.items[0].score_result.assessments}
    assert rows[ab.id].status == ("met" if retained else "unknown")
    if retained:
        assert rows[ab.id].evidence_ids == ["e-ab"]
    if old_evidence in {
        "contradicted",
        "different_label",
        "jd_label_correction",
        "shared_alternate_correction",
    }:
        assert rows[ab.id].unknown_reason == "conflicting_evidence"
        assert rows[ab.id].coefficient == 0
        assert rows[ab.id].evidence_ids == ["e-ab", "e-correction"]
        gap = next(g for g in second.items[0].report.gaps if g.requirement_id == ab.id)
        assert gap.evidence_ids == ["e-ab", "e-correction"]
        replayed = completed_diagnosis(world, second_request)
        assert replayed.items[0].score_result == second.items[0].score_result
    assert rows[valuation.id].status == "met" and rows[valuation.id].evidence_ids == ["e-val"]
    assert world.repo.owned(world.repo.diagnoses, first.id, world.sid).value == first
    assert world.gateway.calls == []


def test_standalone_manual_criterion_can_be_verified_after_a_conflict_is_resolved(world):
    ab = manual_requirement("r-ab", "A/B 实验")
    requirement = Requirement.model_validate(
        {
            **ab.model_dump(),
            "operator": "criteria",
            "target": "manual",
            "condition": {
                "any_of": [
                    {
                        "scope": "profile",
                        "all_of": [
                            {
                                "field": "manual",
                                "comparison": "eq",
                                "value": ab.target,
                                "quote": ab.quote,
                            }
                        ],
                    }
                ]
            },
        }
    )
    baseline = manual_review_baseline(world, [requirement])
    content = world.profile.content.model_copy(deep=True)
    add_verified_example(content, "ab", ab.target, "参与 A/B 实验，随机分组并汇总转化率。")
    add_verified_example(content, "correction", ab.target, "更正：没有参与过 A/B 实验。")
    content.facts[-1].polarity = "negative"
    conflict = completed_diagnosis(world, followup_rerun(world, baseline, content, ab.id, "e-ab"))
    assert conflict.verified_requirements == []
    row = next(a for a in conflict.items[0].score_result.assessments if a.requirement_id == ab.id)
    assert row.unknown_reason == "conflicting_evidence"
    assert row.evidence_ids == ["e-ab", "e-correction"]

    content.evidence.pop()
    content.facts.pop()
    resolved = completed_diagnosis(world, followup_rerun(world, conflict, content, ab.id, "e-ab"))
    assert resolved.verified_requirements == [
        VerifiedRequirement(requirement_id=ab.id, evidence_id="e-ab", fact_id="f-ab")
    ]
    row = next(a for a in resolved.items[0].score_result.assessments if a.requirement_id == ab.id)
    assert row.status == "met" and row.evidence_ids == ["e-ab"]


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


@pytest.mark.parametrize("short_answer", ["两年", "是的", "没有"])
def test_short_answer_after_worker_recovery_keeps_the_question_as_readonly_context(
    world, short_answer
):
    asked = world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
    asyncio.run(world.worker.run_once())
    question = task(world, asked.task_id).result.assistant_message
    answered = world.platform.chat(
        world.sid,
        world.profile.id,
        request(world, questions=False, content=short_answer),
        uuid4().hex,
    )
    first = world.store.claim()
    first_history = world.store.load(first).history
    at = world.repo.clock() + timedelta(seconds=61)
    world.repo.clock = lambda: at
    second = world.store.claim()
    assert second.task_id == first.task_id and second.attempt == 2
    assert world.store.load(second).history == first_history
    asyncio.run(world.worker.execute(second))
    assert task(world, answered.task_id).status == "succeeded"
    sent = world.gateway.calls[-1]
    assert sent["user_text"] == short_answer
    assert sent["history_assistant_messages"] == [
        {"message_id": first_history[0].id, "content": question}
    ]
    assert sent["history_order"] == [first_history[0].id]
    assert sent["history_user_messages"] == []
    assert (
        world.repo.version(world.repo.profiles, world.profile.id, world.sid).content
        == world.profile.content
    )


@pytest.mark.parametrize("rounds", [7, 12])
def test_worker_keeps_ten_messages_per_role_instead_of_ten_total(world, rounds):
    for index in range(rounds):
        submitted = world.platform.chat(
            world.sid,
            world.profile.id,
            request(world, questions=False, content=f"合成答复第 {index + 1} 轮。"),
            uuid4().hex,
        )
        asyncio.run(world.worker.run_once())
        assert task(world, submitted.task_id).status == "succeeded"
    messages = world.repo.owned(world.repo.profiles, world.profile.id, world.sid).messages
    assert len(messages) == rounds * 2
    submitted = world.platform.chat(
        world.sid,
        world.profile.id,
        request(world, questions=False, content="这是下一轮合成回答。"),
        uuid4().hex,
    )
    lease = world.store.claim()
    history = world.store.load(lease).history
    expected_users = [m.id for m in messages if m.role == "user"][-10:]
    expected_assistants = [m.id for m in messages if m.role == "assistant"][-10:]
    assert len(history) == 2 * min(rounds, 10)
    asyncio.run(world.worker.execute(lease))
    assert task(world, submitted.task_id).status == "succeeded"
    sent = world.gateway.calls[-1]
    assert [m["source_id"] for m in sent["history_user_messages"]] == expected_users
    assert [m["message_id"] for m in sent["history_assistant_messages"]] == expected_assistants
    assert sent["history_order"] == [m.id for m in history]
    assert world.repo.version(world.repo.profiles, world.profile.id, world.sid) == world.profile


def test_equal_clock_ticks_keep_question_answer_and_next_question_in_order(world, monkeypatch):
    instant = world.repo.clock()
    world.repo.clock = lambda: instant

    # Force UUID order to disagree with conversation order: UUIDs are identifiers,
    # not a reliable sequence for messages created in the same clock tick.
    def process_with_assistant_id(assistant_id):
        lease = world.store.claim()
        with monkeypatch.context() as scoped:
            scoped.setattr("app.platform.jobs.store.new_id", lambda: assistant_id)
            asyncio.run(world.worker.execute(lease))

    asked = world.platform.chat(world.sid, world.profile.id, request(world), uuid4().hex)
    process_with_assistant_id("ffffffff-ffff-4fff-8fff-ffffffffffff")
    answered = world.platform.chat(
        world.sid,
        world.profile.id,
        request(world, questions=False, content="两年"),
        uuid4().hex,
    )
    process_with_assistant_id("00000000-0000-4000-8000-000000000001")
    assert task(world, asked.task_id).status == task(world, answered.task_id).status == "succeeded"
    with world.repo.engine.connect() as connection:
        user_id = connection.scalar(
            select(db.messages.c.id).where(
                db.messages.c.task_id == answered.task_id, db.messages.c.role == "user"
            )
        )
    expected = [
        "ffffffff-ffff-4fff-8fff-ffffffffffff",
        user_id,
        "00000000-0000-4000-8000-000000000001",
    ]
    world.platform.chat(
        world.sid,
        world.profile.id,
        request(world, questions=False, content="是的"),
        uuid4().hex,
    )
    lease = world.store.claim()
    history = world.store.load(lease).history
    assert [message.id for message in history] == expected
    assert [message.role for message in history] == ["assistant", "user", "assistant"]
    public_history = world.repo.owned(world.repo.profiles, world.profile.id, world.sid).messages
    assert [message.id for message in public_history] == expected
    # A recovered task reads the same chronology from the persisted store.
    later = instant + timedelta(seconds=61)
    world.repo.clock = lambda: later
    recovered = world.store.claim()
    assert recovered.task_id == lease.task_id and recovered.attempt == 2
    assert recovered.token != lease.token
    assert world.store.load(recovered).history == history
    with pytest.raises(LeaseLost):
        world.store.load(lease)
