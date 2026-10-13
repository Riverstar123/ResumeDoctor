"""M3 语义校验：正常样例通过，伪造引用/重复编号/非法日期被拒绝。"""

import copy
from datetime import date
from itertools import permutations

import pytest

from app.contracts import JobContent, ProfileContent, Requirement
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


@pytest.mark.parametrize("operator", ["has_skill", "has_evidence", "manual_review"])
def test_subject_is_rejected_for_every_non_min_months_operator(operator):
    data = job_data()
    data["requirements"][0].update(operator=operator, subject="Python")
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_SUBJECT"


def test_subject_is_rejected_for_degree_at_least():
    """学历分支曾用 elif 跳过通用 subject 约束（PR #44 评审 P2）。"""
    data = job_data()
    data["requirements"][3]["subject"] = "Python"
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


# --- 同结构不同原文：不能静默合并（PR #44 评审 P1）------------------------


def test_same_structure_with_different_quote_is_rejected():
    data = job_data()
    data["requirements"][2]["target"] = "Python"  # 让 r3 与 r1 的结构键相同
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "REQUIREMENT_CONFLICT"


def test_requirement_conflict_does_not_depend_on_order():
    """重排要求顺序后必须报同一个冲突，否则分数会随顺序变化。"""
    data = job_data()
    data["requirements"][2]["target"] = "Python"
    data["requirements"].reverse()
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "REQUIREMENT_CONFLICT"


def test_oversized_min_months_target_reports_intake_error():
    """超长数字串不能让裸 ValueError 逃出去（PR #44 评审 P2）。"""
    data = job_data()
    data["requirements"][0].update(operator="min_months", subject="Python", target="9" * 5000)
    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "INVALID_MIN_MONTHS_TARGET"


# --- ignored 状态冲突：不能静默改变计分分母（PR #44 复审 P1）----------------


def test_same_requirement_with_opposite_ignored_is_rejected():
    data = job_data()
    duplicate = copy.deepcopy(data["requirements"][0])
    duplicate["id"] = "r9"
    duplicate["ignored"] = True
    duplicate["ignore_reason"] = "用户明确排除该要求"
    data["requirements"].append(duplicate)

    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "REQUIREMENT_CONFLICT"


def test_ignored_conflict_does_not_depend_on_order():
    """把不计分的那条放到前面，仍必须报同一个冲突。"""
    data = job_data()
    duplicate = copy.deepcopy(data["requirements"][0])
    duplicate["id"] = "r9"
    duplicate["ignored"] = True
    duplicate["ignore_reason"] = "用户明确排除该要求"
    data["requirements"].insert(0, duplicate)

    with pytest.raises(IntakeError) as error:
        check_job(data)
    assert error.value.code == "REQUIREMENT_CONFLICT"


def test_different_ignore_reason_is_only_a_warning():
    """两条都不计分、只是原因写法不同：提示但不阻断（PR #44 复审）。"""
    data = job_data()
    data["requirements"][0].update(ignored=True, ignore_reason="性别相关，不计分")
    duplicate = copy.deepcopy(data["requirements"][0])
    duplicate["id"] = "r9"
    duplicate["ignore_reason"] = "用户明确排除"
    data["requirements"].append(duplicate)

    result = check_job(data)

    assert len(result.content.requirements) == 4
    assert any("排除原因不同" in warning for warning in result.warnings)


def test_target_case_difference_is_only_a_warning():
    """仅 target 写法不同：按既定取舍只提示，不报错。"""
    data = job_data()
    duplicate = copy.deepcopy(data["requirements"][0])
    duplicate["id"] = "r9"
    duplicate["target"] = "python"
    data["requirements"].append(duplicate)

    result = check_job(data)

    assert len(result.content.requirements) == 4
    assert any("写法不同" in warning for warning in result.warnings)


# --- 重排不变性与字段守卫 ----------------------------------------------------


def test_requirement_validation_is_order_independent():
    """正常数据重排任意顺序，校验结果必须一致（PR #44 两轮评审的共同主题）。"""
    data = job_data()
    expected: list[str] | None = None
    for order in permutations(range(len(data["requirements"]))):
        shuffled = copy.deepcopy(data)
        shuffled["requirements"] = [data["requirements"][index] for index in order]
        ids = sorted(item.id for item in check_job(shuffled).content.requirements)
        if expected is None:
            expected = ids
        assert ids == expected


def test_requirement_fields_are_all_accounted_for():
    """Requirement 增减字段时必须同步去重策略，防止再次漏掉某个字段的差异。"""
    accounted = {
        "id",  # 每条要求自己的标识，不参与比较
        "quote",  # 进比较键：原文不同即视为不同要求
        "category",  # 进比较键
        "operator",  # 进比较键
        "target",  # 进比较键；写法差异只提示
        "subject",  # 同上
        "importance",  # 特殊处理：冲突保留 must
        "ignored",  # 特殊处理：状态相反即报冲突
        "ignore_reason",  # 特殊处理：仅提示，不阻断
    }
    assert set(Requirement.model_fields) == accounted, (
        "Requirement 字段有变化，请同步 _requirement_key 与 _merge_duplicate_requirements"
    )
