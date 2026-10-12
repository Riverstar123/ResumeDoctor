import asyncio

import pytest
from report_contract import ReportContractError, check_report_contract

from app.contracts import DiagnosisItem, Job, ModelMetadata, Profile, ReportContent, Suggestion
from app.contracts.ports import ReportingPort, TaskContext
from app.scoring import assess_requirements, calculate_score
from app.tools.check_contracts import example_validator


def snapshots(example):
    return (
        Profile.model_validate(example("profile.json")),
        Job.model_validate(example("job.json")),
        DiagnosisItem.model_validate(example("diagnosis-item.json")),
    )


def test_repository_report_and_score_only_are_consistent(example):
    p, j, item = snapshots(example)
    check_report_contract(p.content, j.content, item)
    item.status, item.report = "score_only", None
    check_report_contract(p.content, j.content, item)


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("score", "score differs"),
        ("evidence", "evidence is missing"),
        ("gap_kind", "gap kind"),
        ("requirement", "unscored requirement"),
        ("missing_gap", "mandatory gap"),
        ("invented_number", "concrete numbers"),
        ("no_input_flag", "request user input"),
        ("missing_report", "needs report"),
        ("duplicate_gap", "duplicate gap"),
        ("duplicate_assessment", "duplicate assessments"),
        ("duplicate_dimension", "duplicate score dimensions"),
    ],
)
def test_invalid_report_outputs_are_rejected(example, mutation, match):
    p, j, item = snapshots(example)
    if mutation == "score":
        item.score_result.score = 100
    elif mutation == "evidence":
        item.report.suggestions[0].evidence_ids = ["invented-evidence"]
    elif mutation == "gap_kind":
        item.report.gaps[0].kind = "explicit_gap"
    elif mutation == "requirement":
        item.report.actions[0].requirement_id = "another-job-requirement"
    elif mutation == "missing_gap":
        item.report.gaps = []
    elif mutation == "invented_number":
        item.report.suggestions[0].revised = "提升业绩 50%。"
    elif mutation == "no_input_flag":
        item.report.suggestions[0].original = None
        item.report.suggestions[0].requires_user_input = False
    elif mutation == "missing_report":
        item.report = None
    elif mutation == "duplicate_gap":
        item.report.gaps *= 2
    elif mutation == "duplicate_assessment":
        item.score_result.assessments.append(item.score_result.assessments[0])
    else:
        item.score_result.dimensions.append(item.score_result.dimensions[0])
    with pytest.raises(ReportContractError, match=match):
        check_report_contract(p.content, j.content, item)


def test_fake_reporting_port_model_switch_preserves_frozen_score(example, design):
    """Protocol integration only. No claim to exercise E's not-yet-delivered implementation."""
    p, j, template = snapshots(example)
    baseline = calculate_score(assess_requirements(p.content, j.content))

    class SyntheticReporter:
        async def generate_report(
            self, profile_snapshot, job_snapshot, score_result, model_metadata, *, context
        ):
            assert profile_snapshot == p and job_snapshot == j
            assert score_result == baseline
            assert model_metadata.model_id == context.model_id
            report = ReportContent.model_validate(template.report.model_dump())
            report.summary = f"合成报告，仅验证端口；模型选择 {context.model_id}。"
            return report

        def export_markdown(self, item):
            return item.report.summary

    reporter: ReportingPort = SyntheticReporter()
    assert isinstance(reporter, ReportingPort)

    async def consume():
        results = []
        for model_id in ("synthetic-model-a", "synthetic-model-b"):
            score_input = baseline.model_copy(deep=True)
            metadata = ModelMetadata.model_validate(template.model_metadata.model_dump())
            metadata.model_id = model_id
            report = await reporter.generate_report(
                p, j, score_input, metadata, context=TaskContext(model_id)
            )
            item = template.model_copy(deep=True)
            item.score_result, item.report, item.model_metadata = score_input, report, metadata
            example_validator(design, "DiagnosisItem").validate(item.model_dump(mode="json"))
            check_report_contract(
                p.content, j.content, item, expected_score=baseline, expected_model_id=model_id
            )
            results.append(item)
        return results

    first, second = asyncio.run(consume())
    assert first.score_result.model_dump() == second.score_result.model_dump()
    assert first.report.summary != second.report.summary


def test_reporter_cannot_mutate_frozen_reasons_or_change_chosen_model(example):
    p, j, item = snapshots(example)
    frozen = item.score_result.model_copy(deep=True)
    item.score_result.assessments[0].reason = "模型私自改写评分事实。"
    with pytest.raises(ReportContractError, match="mutated frozen"):
        check_report_contract(p.content, j.content, item, expected_score=frozen)
    item.score_result = frozen
    with pytest.raises(ReportContractError, match="different model"):
        check_report_contract(p.content, j.content, item, expected_model_id="other-model")


@pytest.mark.parametrize(
    "revised",
    [
        "在项目中[提升业绩50%]。",
        "完成[50%]的业绩提升。",
        "成果[请填写真实数据50%]。",
    ],
)
def test_brackets_cannot_hide_unsupported_concrete_numbers(example, design, revised):
    p, j, item = snapshots(example)
    item.report.suggestions[0].revised = revised
    example_validator(design, "DiagnosisItem").validate(item.model_dump(mode="json"))
    with pytest.raises(ReportContractError, match="concrete numbers"):
        check_report_contract(p.content, j.content, item)


def test_explicit_user_fill_placeholder_is_valid_but_requires_input(example, design):
    p, j, item = snapshots(example)
    item.report.suggestions[0].revised = "在项目中产生[请填写真实数据]的结果。"
    item.report.suggestions[0].requires_user_input = True
    example_validator(design, "DiagnosisItem").validate(item.model_dump(mode="json"))
    check_report_contract(p.content, j.content, item)
    item.report.suggestions[0].requires_user_input = False
    with pytest.raises(ReportContractError, match="placeholder.*user input"):
        check_report_contract(p.content, j.content, item)


def test_related_profile_evidence_can_support_future_learning_suggestion(example, design):
    p, j, item = snapshots(example)
    frozen = item.score_result.model_copy(deep=True)
    item.report.suggestions.append(
        Suggestion(
            requirement_id="r3",
            original=None,
            evidence_ids=["e1"],
            requires_user_input=True,
            revised="以已有 Python 项目为练习对象完成容器化，完成后再补充真实 Docker 使用证据。",
            rationale="仅建议将来练习，不断言现在已掌握 Docker。",
        )
    )
    example_validator(design, "DiagnosisItem").validate(item.model_dump(mode="json"))
    check_report_contract(p.content, j.content, item, expected_score=frozen)
    assert item.score_result.assessments[2].status == "unknown"
    assert item.score_result == frozen
    item.report.suggestions[-1].evidence_ids = ["missing-from-profile"]
    with pytest.raises(ReportContractError, match="evidence is missing"):
        check_report_contract(p.content, j.content, item)


def test_direct_gap_evidence_must_still_agree_with_assessment(example):
    p, j, item = snapshots(example)
    item.report.gaps[1].evidence_ids = ["e1"]
    with pytest.raises(ReportContractError, match="gap evidence"):
        check_report_contract(p.content, j.content, item)


def test_bracketed_numbers_with_real_support_are_valid(example):
    p, j, item = snapshots(example)
    p.content.evidence[1].quote += " 完全虚构：原文明确记录提升 50%。"
    item.report.suggestions[0].revised = "合成记录中[提升50%]，引用同一已提供原文。"
    check_report_contract(p.content, j.content, item)
