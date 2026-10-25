"""登记 fake 模型与 M3/M4/M5 的实际端口互操作；不调用真实供应商。"""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from app.contracts import DiagnosisItem, Job, Profile, ProfileContent
from app.contracts.ports import ExtractedDocument, TaskContext, TextSegment
from app.intake import GatewayIntake
from app.llm import FakeModelDirectory, GatewayError, task_output_schema
from app.platform.demo_gateway import JOB_TEXTS, PROFILE_TEXT, IntegrationFakeGateway
from app.reporting import ReportService

CONTEXT = TaskContext("demo-model-a")


async def no_sleep(_seconds):
    pass


def gateway(**kwargs):
    return IntegrationFakeGateway(FakeModelDirectory(), sleep=no_sleep, **kwargs)


def run(awaitable):
    return asyncio.run(awaitable)


def empty():
    return ProfileContent(overview="", as_of_month="2026-09", facts=[], evidence=[])


def test_document_sources_and_locations_are_bound_per_task():
    model = gateway()
    extracted = ExtractedDocument(
        text=PROFILE_TEXT.strip(),
        segments=tuple(
            TextSegment(text, f"段落 {index}")
            for index, text in enumerate(PROFILE_TEXT.strip().splitlines(), 1)
        ),
        warnings=(),
    )
    outputs = []
    for _ in range(2):
        source_id = str(uuid4())
        result = run(
            GatewayIntake(model, source_id=source_id).build_document_profile(
                extracted, context=CONTEXT
            )
        )
        assert {e.source_id for e in result.evidence} == {source_id}
        assert {e.source_type for e in result.evidence} == {"document"}
        assert [e.locator for e in result.evidence] == ["段落 1", "段落 2", "段落 3"]
        outputs.append(result)
    assert not {e.id for e in outputs[0].evidence} & {e.id for e in outputs[1].evidence}
    outputs[0].facts[0].label = "修改第一个结果"
    assert outputs[1].facts[0].label == "Python"


def test_chat_accumulates_user_sources_and_preserves_existing_snapshot():
    model, content = gateway(), empty()
    source_ids = []
    for text in PROFILE_TEXT.strip().splitlines():
        old = content.model_copy(deep=True)
        source_id = str(uuid4())
        source_ids.append(source_id)
        result = run(
            GatewayIntake(model, source_id=source_id).advance_conversation(
                text, content, [], context=CONTEXT
            )
        )
        assert content == old
        assert result.profile_content.facts[: len(old.facts)] == old.facts
        assert result.profile_content.evidence[: len(old.evidence)] == old.evidence
        content = result.profile_content
    assert {e.source_id for e in content.evidence} == set(source_ids)
    assert {e.source_type for e in content.evidence} == {"message"}
    repeated = run(
        GatewayIntake(model, source_id=str(uuid4())).advance_conversation(
            PROFILE_TEXT, content, [], context=CONTEXT
        )
    )
    assert repeated.profile_content == content


def test_chat_accepts_full_profile_and_does_not_reuse_other_conversation_state():
    model = gateway()
    first = run(
        GatewayIntake(model, source_id=str(uuid4())).advance_conversation(
            PROFILE_TEXT, empty(), [], context=CONTEXT
        )
    ).profile_content
    source_id = str(uuid4())
    second = run(
        GatewayIntake(model, source_id=source_id).advance_conversation(
            PROFILE_TEXT.strip().splitlines()[1], empty(), [], context=CONTEXT
        )
    ).profile_content
    assert len(first.facts) == 3
    assert [fact.label for fact in second.facts] == ["SQL"]
    assert {e.source_id for e in second.evidence} == {source_id}


def test_five_jobs_are_validated_independently_and_keep_company_context():
    intake = GatewayIntake(gateway())
    jobs = [
        run(intake.extract_job(text, f"独立背景 {index}", context=CONTEXT))
        for index, text in enumerate(JOB_TEXTS)
    ]
    assert len({job.title for job in jobs}) == 5
    assert [job.requirements[0].target for job in jobs] == [
        "Python",
        "Kubernetes",
        "Python",
        "SQL",
        "Docker",
    ]
    assert [len(job.requirements) for job in jobs] == [4, 1, 1, 1, 1]
    for index, job in enumerate(jobs):
        assert job.company_context == f"独立背景 {index}"
        assert all(requirement.quote in JOB_TEXTS[index] for requirement in job.requirements)
    jobs[2].requirements[0].target = "被修改"
    assert jobs[0].requirements[0].target == "Python"
    again = run(intake.extract_job(JOB_TEXTS[2], "", context=CONTEXT))
    assert again.requirements[0].target == "Python"


@pytest.mark.parametrize("kind", ["profile", "chat", "job"])
def test_unregistered_material_fails_explicitly(kind):
    intake = GatewayIntake(gateway(), source_id=str(uuid4()))
    operation = {
        "profile": lambda: intake.build_profile("未经登记的任意简历", "document", context=CONTEXT),
        "chat": lambda: intake.advance_conversation("任意对话", empty(), [], context=CONTEXT),
        "job": lambda: intake.extract_job("任意岗位", "", context=CONTEXT),
    }[kind]
    with pytest.raises(GatewayError) as error:
        run(operation())
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert "未登记" in str(error.value)


def test_document_profile_accepts_only_whitespace_normalization():
    intake = GatewayIntake(gateway(), source_id=str(uuid4()))
    profile = run(
        intake.build_profile(
            "  " + PROFILE_TEXT.replace("\n", "  ") + "  ", "document", context=CONTEXT
        )
    )
    assert len(profile.facts) == 3
    with pytest.raises(GatewayError):
        run(intake.build_profile(PROFILE_TEXT + "新增事实", "document", context=CONTEXT))


@pytest.mark.parametrize(
    "behavior,code",
    [
        ("invalid_json", "MODEL_OUTPUT_INVALID"),
        ("provider_unavailable", "PROVIDER_UNAVAILABLE"),
        ("timeout", "MODEL_TIMEOUT"),
    ],
)
def test_m5_failures_and_retry_budget_are_retained(behavior, code):
    model = gateway(failures={"job_extract": behavior})
    with pytest.raises(GatewayError) as error:
        run(
            model.generate_structured(
                "job_extract",
                {"raw_text": JOB_TEXTS[0]},
                task_output_schema("job_extract"),
                0.01,
                context=CONTEXT,
            )
        )
    assert error.value.code == code
    assert model.calls[-1].attempts == (1 if behavior == "timeout" else 2)


def test_report_service_uses_frozen_score_and_actual_gateway_metadata(example):
    model = gateway()
    profile = Profile.model_validate(example("profile.json"))
    job = Job.model_validate(example("job.json"))
    item = DiagnosisItem.model_validate(example("diagnosis-item.json"))
    frozen = deepcopy(item.score_result)
    metadata = model.directory.resolve(
        CONTEXT.model_id, "diagnosis_report", item.model_metadata.generated_at
    )
    report = run(
        ReportService(model).generate_report(
            profile, job, item.score_result, metadata, context=CONTEXT
        )
    )
    assert item.score_result == frozen
    assert report.gaps
    assert model.calls[-1].task_name == "diagnosis_report"
    assert model.calls[-1].prompt_version == "report-v1"
    assert "演示数据" in report.summary


def test_schema_and_model_validation_remain_owned_by_m5():
    model = gateway()
    with pytest.raises(GatewayError) as error:
        run(
            model.generate_structured(
                "job_extract",
                {"raw_text": JOB_TEXTS[0]},
                task_output_schema("profile_extract"),
                1.0,
                context=CONTEXT,
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert model.calls == []
    with pytest.raises(GatewayError) as error:
        run(
            model.generate_structured(
                "job_extract",
                {"raw_text": JOB_TEXTS[0]},
                task_output_schema("job_extract"),
                1.0,
                context=TaskContext("unavailable"),
            )
        )
    assert error.value.code == "MODEL_UNAVAILABLE"
