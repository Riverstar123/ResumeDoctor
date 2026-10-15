"""合成端口：固定输出必须与仓库样例一致，且本身满足引用约束。"""

import asyncio
import io

import pytest

from app.contracts.ports import IntakePort, TaskContext
from app.intake import (
    KUBERNETES_JOB_RAW_TEXT,
    SYNTHETIC_JOB_FIXTURES,
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCE_TEXT,
    SYNTHETIC_SOURCES,
    IntakeError,
    SyntheticIntake,
    synthetic_job_content,
    synthetic_profile_content,
)

CONTEXT = TaskContext(model_id="demo-model-a")


def test_synthetic_profile_matches_repository_example(example):
    expected = example("profile.json")["content"]
    assert synthetic_profile_content().model_dump(mode="json") == expected


def test_synthetic_job_matches_repository_example(example):
    expected = example("job.json")
    assert synthetic_job_content().model_dump(mode="json") == expected["content"]
    assert SYNTHETIC_JOB_RAW_TEXT == expected["raw_text"]


def test_port_satisfies_intake_protocol():
    assert isinstance(SyntheticIntake(), IntakePort)


def test_build_profile_returns_the_fixed_profile():
    result = asyncio.run(
        SyntheticIntake().build_profile("用户随便写的一段经历", "manual", context=CONTEXT)
    )
    assert result == synthetic_profile_content()


def test_extract_job_returns_the_fixed_job():
    result = asyncio.run(
        SyntheticIntake().extract_job(SYNTHETIC_JOB_RAW_TEXT, "", context=CONTEXT)
    )
    assert result == synthetic_job_content()


def test_extract_document_returns_text_with_locator():
    document = asyncio.run(SyntheticIntake().extract_document(io.BytesIO(b""), "application/pdf"))
    assert document.text == SYNTHETIC_SOURCE_TEXT
    assert document.segments[0].locator == "page:1"
    assert document.warnings == ()


def test_advance_conversation_returns_message_and_profile():
    result = asyncio.run(
        SyntheticIntake().advance_conversation(
            "我做过一个数据清洗项目", synthetic_profile_content(), [], context=CONTEXT
        )
    )
    assert result.assistant_message
    assert result.profile_content == synthetic_profile_content()


def test_every_synthetic_quote_is_inside_its_source():
    for item in synthetic_profile_content().evidence:
        assert item.quote in SYNTHETIC_SOURCES[item.source_id]


def test_every_job_fixture_quote_matches_its_own_raw_text():
    for raw_text, build in SYNTHETIC_JOB_FIXTURES.items():
        for requirement in build().requirements:
            assert requirement.quote in raw_text


# --- 双 fixture：集成需要两份不同 JD 独立提取（#13 集成发现的缺口）---------


def test_second_fixture_is_returned_for_its_own_raw_text():
    result = asyncio.run(
        SyntheticIntake().extract_job(KUBERNETES_JOB_RAW_TEXT, "", context=CONTEXT)
    )

    assert result.title == "平台运维合成岗位"
    assert [item.target for item in result.requirements] == ["Kubernetes"]


def test_two_fixtures_do_not_bleed_into_each_other():
    intake = SyntheticIntake()
    first = asyncio.run(intake.extract_job(SYNTHETIC_JOB_RAW_TEXT, "", context=CONTEXT))
    second = asyncio.run(intake.extract_job(KUBERNETES_JOB_RAW_TEXT, "", context=CONTEXT))

    assert {item.target for item in first.requirements} == {
        "Python",
        "SQL",
        "Docker",
        "bachelor",
    }
    assert {item.target for item in second.requirements} == {"Kubernetes"}


def test_unknown_raw_text_fails_instead_of_reusing_a_fixture():
    with pytest.raises(IntakeError) as error:
        asyncio.run(
            SyntheticIntake().extract_job("这是一份没有 fixture 的岗位描述。", "", context=CONTEXT)
        )

    assert error.value.code == "UNKNOWN_SYNTHETIC_INPUT"


def test_company_context_is_carried_into_the_result():
    result = asyncio.run(
        SyntheticIntake().extract_job(
            KUBERNETES_JOB_RAW_TEXT, "某云服务商的运维团队。", context=CONTEXT
        )
    )

    assert result.company_context == "某云服务商的运维团队。"
