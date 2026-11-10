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
    Evidence,
    Fact,
    Gap,
    MessageCreate,
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
