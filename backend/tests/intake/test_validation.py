"""M3 语义校验：正常样例通过，伪造引用/重复编号/非法日期被拒绝。"""

import copy
from datetime import date

import pytest

from app.contracts import JobContent, ProfileContent
from app.intake import (
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCES,
    IntakeError,
    synthetic_job_content,
    synthetic_profile_content,
    validate_job_content,
    validate_profile_content,
)


def profile_data() -> dict:
    return synthetic_profile_content().model_dump()


def job_data() -> dict:
    return synthetic_job_content().model_dump()


def check_profile(data: dict):
    return validate_profile_content(ProfileContent.model_validate(data), SYNTHETIC_SOURCES)


def check_job(data: dict):
    return validate_job_content(JobContent.model_validate(data), SYNTHETIC_JOB_RAW_TEXT)


# --- 正常路径 ---------------------------------------------------------------


def test_synthetic_profile_passes_validation():
    result = check_profile(profile_data())
    assert result.warnings == ()
    assert [fact.id for fact in result.content.facts] == ["f1", "f2", "f3"]


def test_synthetic_job_passes_validation():
    result = check_job(job_data())
    assert result.warnings == ()
    assert [item.id for item in result.content.requirements] == ["r1", "r2", "r3", "r4"]


def test_as_of_month_accepts_injected_reference_day():
    result = validate_profile_content(
        ProfileContent.model_validate(profile_data()),
        SYNTHETIC_SOURCES,
        today=date(2026, 9, 30),
    )
    assert result.content.as_of_month == "2026-09"


# --- 档案：引用与编号 --------------------------------------------------------


def test_rewritten_quote_is_rejected():
    data = profile_data()
    data["evidence"][0]["quote"] = "精通 Python 并带过团队"
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "QUOTE_NOT_IN_SOURCE"


def test_evidence_from_unknown_source_is_rejected():
    data = profile_data()
    data["evidence"][0]["source_id"] = "not-in-this-request"
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "UNKNOWN_SOURCE"


def test_fact_referencing_missing_evidence_is_rejected():
    data = profile_data()
    data["facts"][0]["evidence_ids"] = ["e9"]
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "UNKNOWN_EVIDENCE_REFERENCE"


def test_duplicate_fact_id_is_rejected():
    data = profile_data()
    data["facts"].append(copy.deepcopy(data["facts"][0]))
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "DUPLICATE_LOCAL_ID"


def test_duplicate_evidence_id_is_rejected():
    data = profile_data()
    data["evidence"].append(copy.deepcopy(data["evidence"][1]))
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "DUPLICATE_LOCAL_ID"


# --- 档案：日期与学历 --------------------------------------------------------


def test_reversed_month_range_is_rejected():
    data = profile_data()
    data["facts"][0]["start_month"] = "2026-05"
    data["facts"][0]["end_month"] = "2026-03"
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "INVALID_MONTH_RANGE"


def test_zero_length_month_range_is_rejected():
    data = profile_data()
    data["facts"][0]["start_month"] = "2026-05"
    data["facts"][0]["end_month"] = "2026-05"
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "INVALID_MONTH_RANGE"


def test_future_as_of_month_is_rejected():
    data = profile_data()
    data["as_of_month"] = "2099-01"
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "AS_OF_MONTH_IN_FUTURE"


def test_unknown_education_value_is_rejected():
    data = profile_data()
    data["facts"][2]["value"] = "本科"
    with pytest.raises(IntakeError) as error:
        check_profile(data)
    assert error.value.code == "INVALID_EDUCATION_VALUE"


# --- 岗位：引用与语义 --------------------------------------------------------


def test_job_quote_outside_raw_text_is_rejected():
    data = job_data()
    data["requirements"][0]["quote"] = "精通 Python 并且能独立带项目"
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "QUOTE_NOT_IN_SOURCE"


def test_duplicate_requirement_id_is_rejected():
    data = job_data()
    data["requirements"].append(copy.deepcopy(data["requirements"][0]))
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "DUPLICATE_LOCAL_ID"


def test_ignored_requirement_needs_reason():
    data = job_data()
    data["requirements"][0]["ignored"] = True
    data["requirements"][0]["ignore_reason"] = None
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "MISSING_IGNORE_REASON"


def test_min_months_needs_subject():
    data = job_data()
    data["requirements"][0].update(operator="min_months", target="24", subject=None)
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_SUBJECT"


def test_min_months_target_must_be_positive_integer():
    data = job_data()
    data["requirements"][0].update(operator="min_months", target="两年", subject="Python")
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_MIN_MONTHS_TARGET"


def test_min_months_zero_is_rejected():
    data = job_data()
    data["requirements"][0].update(operator="min_months", target="0", subject="Python")
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_MIN_MONTHS_TARGET"


def test_degree_target_must_be_comparable():
    data = job_data()
    data["requirements"][3]["target"] = "other"
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_DEGREE_TARGET"


def test_subject_is_only_allowed_for_min_months():
    data = job_data()
    data["requirements"][0]["subject"] = "Python"
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_SUBJECT"


# --- 岗位：重复要求合并 ------------------------------------------------------


def test_duplicate_requirements_are_merged():
    data = job_data()
    duplicate = copy.deepcopy(data["requirements"][0])
    duplicate["id"] = "r9"
    data["requirements"].append(duplicate)

    result = check_job(data)

    assert [item.id for item in result.content.requirements] == ["r1", "r2", "r3", "r4"]
    assert any("重复" in warning for warning in result.warnings)


def test_importance_conflict_keeps_must():
    data = job_data()
    duplicate = copy.deepcopy(data["requirements"][2])
    duplicate["id"] = "r9"
    duplicate["importance"] = "must"
    data["requirements"].append(duplicate)

    result = check_job(data)

    docker = next(item for item in result.content.requirements if item.target == "Docker")
    assert docker.importance == "must"
    assert any("重要性冲突" in warning for warning in result.warnings)


def test_different_targets_are_not_merged():
    data = job_data()
    extra = copy.deepcopy(data["requirements"][0])
    extra["id"] = "r9"
    extra["target"] = "Java"
    extra["quote"] = "熟悉 Docker 优先。"
    data["requirements"].append(extra)

    result = check_job(data)

    assert len(result.content.requirements) == 5
    assert result.warnings == ()
