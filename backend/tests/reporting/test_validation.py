"""报告语义校验：引用、gap 状态、改分与待填写数字（T18）。"""

import pytest

from app.contracts import ReportContent, Suggestion
from app.reporting import ReportError, validate_report


def clone(report: ReportContent) -> ReportContent:
    return ReportContent.model_validate(report.model_dump(mode="json"))


def check(profile, job, score, report, match):
    with pytest.raises(ReportError, match=match):
        validate_report(report, profile.content, job.content, score)


def test_repository_example_passes(snapshots):
    profile, job, item = snapshots
    validate_report(item.report, profile.content, job.content, item.score_result)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("gap_kind", "gap 类型"),
        ("missing_gap", "缺少必答"),
        ("met_gap", "met 要求"),
        ("duplicate_gap", "gap 重复"),
        ("gap_evidence", "超出该条评分明细"),
        ("unknown_requirement", "未评分要求"),
        ("foreign_evidence", "档案中不存在"),
        ("paraphrased_original", "逐字片段"),
        ("invented_number", "具体数字"),
        ("invented_cn_percent", "具体数字"),
        ("invented_cn_quantity", "具体数字"),
        ("invented_cn_one_year", "具体数字"),
        ("invented_cn_one_time", "具体数字"),
        ("invented_cn_positional", "具体数字"),
        ("placeholder_without_flag", "占位符"),
        ("no_evidence_without_flag", "要求用户输入"),
        ("different_score", "不同的分数"),
        ("different_cn_score", "不同的分数"),
        ("different_cn_decimal_score", "不同的分数"),
        ("empty_action", "为空"),
    ],
)
def test_invalid_reports_are_rejected(snapshots, mutation, match):
    profile, job, item = snapshots
    report = clone(item.report)
    if mutation == "gap_kind":
        report.gaps[0].kind = "explicit_gap"
    elif mutation == "missing_gap":
        report.gaps = []
    elif mutation == "met_gap":
        report.gaps[0].requirement_id = "r1"
    elif mutation == "duplicate_gap":
        report.gaps.append(report.gaps[0].model_copy(deep=True))
    elif mutation == "gap_evidence":
        report.gaps[0].evidence_ids = ["e1"]
    elif mutation == "unknown_requirement":
        report.actions[0].requirement_id = "other-job-r1"
    elif mutation == "foreign_evidence":
        report.suggestions[0].evidence_ids = ["invented-evidence"]
    elif mutation == "paraphrased_original":
        report.suggestions[0].original = "我熟悉 SQL。"
    elif mutation == "invented_number":
        report.suggestions[0].revised = "在项目中提升业绩 50%。"
    elif mutation == "invented_cn_percent":
        report.suggestions[0].revised = "在项目中提升业绩百分之五十。"
    elif mutation == "invented_cn_quantity":
        report.suggestions[0].revised = "完成了一百个数据任务。"
    elif mutation == "invented_cn_one_year":
        report.suggestions[0].revised = "使用 SQL，具有一年工作经验。"
    elif mutation == "invented_cn_one_time":
        report.suggestions[0].revised = "使用 SQL，效率提升一倍。"
    elif mutation == "invented_cn_positional":
        report.suggestions[0].revised = "使用 SQL 完成二〇二五条记录。"
    elif mutation == "placeholder_without_flag":
        report.suggestions[0].revised = "在[请填写真实数据]的结果中完成 SQL 应用。"
        report.suggestions[0].requires_user_input = False
    elif mutation == "no_evidence_without_flag":
        report.suggestions[0].evidence_ids = []
        report.suggestions[0].original = None
        report.suggestions[0].requires_user_input = False
    elif mutation == "different_score":
        report.summary = "你的总分是 100 分。"
    elif mutation == "different_cn_score":
        report.summary = "你的总分是一百分。"
    elif mutation == "different_cn_decimal_score":
        report.summary = "你的总分为九十九点九分。"
    else:
        report.actions[0].task = ""

    check(profile, job, item.score_result, report, match)


def test_unknown_outcome_must_use_the_user_fill_template(snapshots):
    profile, job, item = snapshots
    report = clone(item.report)
    report.suggestions[0].original = None
    report.suggestions[0].evidence_ids = []
    report.suggestions[0].revised = "在项目中产生[请填写真实数据]的结果。"
    report.suggestions[0].requires_user_input = True

    validate_report(report, profile.content, job.content, item.score_result)

    report.suggestions[0].requires_user_input = False
    check(profile, job, item.score_result, report, "占位符")


def test_numbers_supported_by_cited_evidence_are_allowed(snapshots):
    profile, job, item = snapshots
    profile.content.evidence[1].quote += " 完全虚构：原文记录提升 50%。"
    report = clone(item.report)
    report.suggestions[0].revised = "引用同一原文，记录中提升[50%]。"

    validate_report(report, profile.content, job.content, item.score_result)


@pytest.mark.parametrize(
    ("evidence_suffix", "revised"),
    [
        (" 完全虚构：记录提升百分之五十。", "引用同一原文，记录中提升 50%。"),
        (" 完全虚构：完成一百个任务。", "完成 100 个任务。"),
        (" 完全虚构：增长两倍。", "增长 2 倍。"),
    ],
)
def test_chinese_numeric_claims_are_normalized_before_comparison(
    snapshots, evidence_suffix, revised
):
    profile, job, item = snapshots
    profile.content.evidence[1].quote += evidence_suffix
    report = clone(item.report)
    report.suggestions[0].revised = revised

    validate_report(report, profile.content, job.content, item.score_result)


@pytest.mark.parametrize(
    ("evidence_suffix", "revised"),
    [
        (" 完全虚构：完成 50 个数据任务。", "提升效率 50%。"),
        (" 完全虚构：提升效率 50%。", "完成 50 个数据任务。"),
    ],
)
def test_percent_and_ordinary_quantity_are_not_interchangeable(snapshots, evidence_suffix, revised):
    profile, job, item = snapshots
    profile.content.evidence[1].quote += evidence_suffix
    report = clone(item.report)
    report.suggestions[0].revised = revised

    check(profile, job, item.score_result, report, "具体数字")


@pytest.mark.parametrize(
    ("evidence_suffix", "revised"),
    [
        (" 完全虚构：具有一年经验，效率提升一倍。", "具有 1 年经验，效率提升 1 倍。"),
        (" 完全虚构：于二〇二四年学习 SQL。", "于 2024 年学习 SQL。"),
        (" 完全虚构：于 2025 年使用 SQL。", "于二〇二五年使用 SQL。"),
    ],
)
def test_explicit_unit_one_and_positional_digits_are_normalized(
    snapshots, evidence_suffix, revised
):
    profile, job, item = snapshots
    profile.content.evidence[1].quote += evidence_suffix
    report = clone(item.report)
    report.suggestions[0].revised = revised

    validate_report(report, profile.content, job.content, item.score_result)


def test_chinese_summary_score_matching_the_frozen_score_is_allowed(snapshots):
    profile, job, item = snapshots
    report = clone(item.report)
    report.summary = "你的总分是六十六点七分。"

    validate_report(report, profile.content, job.content, item.score_result)


@pytest.mark.parametrize(
    "summary",
    [
        "报告与规则评分一致，主要缺口为 SQL 应用证据。",
        "评分一般，需完善 SQL 应用证据。",
    ],
)
def test_one_at_the_start_of_plain_words_is_not_a_score_claim(snapshots, summary):
    profile, job, item = snapshots
    report = clone(item.report)
    report.summary = summary

    validate_report(report, profile.content, job.content, item.score_result)


@pytest.mark.parametrize(
    ("evidence_suffix", "revised"),
    [
        (" 完全虚构：处理 25000 条记录。", "处理 2.5 万条记录。"),
        (" 完全虚构：处理 25000 条记录。", "处理两点五万条记录。"),
        (" 完全虚构：处理两点五万条记录。", "处理 25000 条记录。"),
        (" 完全虚构：处理两点五万条记录。", "处理 2.5 万条记录。"),
    ],
)
def test_decimal_and_wan_suffix_are_one_quantity(snapshots, evidence_suffix, revised):
    profile, job, item = snapshots
    profile.content.evidence[1].quote += evidence_suffix
    report = clone(item.report)
    report.suggestions[0].revised = revised

    validate_report(report, profile.content, job.content, item.score_result)


@pytest.mark.parametrize("phrase", ["千万不要虚构成果。", "万分感谢你的配合。"])
def test_chinese_number_adverbs_are_not_treated_as_claims(snapshots, phrase):
    profile, job, item = snapshots
    report = clone(item.report)
    report.suggestions[0].revised += phrase

    validate_report(report, profile.content, job.content, item.score_result)


def test_related_profile_evidence_can_support_a_suggestion(snapshots):
    profile, job, item = snapshots
    report = clone(item.report)
    report.suggestions.append(
        Suggestion(
            requirement_id="r3",
            original=None,
            revised="以已有 Python 项目为练习对象完成容器化，之后再补充真实 Docker 证据。",
            rationale="只建议未来练习，不断言当前已掌握 Docker。",
            evidence_ids=["e1"],
            requires_user_input=True,
        )
    )
    validate_report(report, profile.content, job.content, item.score_result)
