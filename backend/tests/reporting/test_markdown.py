"""Markdown 导出：成功、score_only、失败、partial 组合与转义（T23）。"""

import copy

from app.contracts import ErrorInfo
from app.reporting import export_markdown


def test_success_export_contains_score_report_and_versions(snapshots):
    _, _, item = snapshots
    text = export_markdown(item)

    assert f"## 岗位 {item.job.id} / v{item.job.version}" in text
    assert "总分：66.7 / 100" in text
    assert "评分规则：coverage-v1" in text
    assert "匹配版本：matcher-v1" in text
    assert "部分差距" in text and "待补充证据" in text
    assert "改写建议" in text and "[真实项目名称]" in text
    assert "下一步行动" in text
    assert "模型选择：demo-model-a" in text
    assert "实际模型：synthetic-fixture" in text


def test_score_only_export_keeps_the_rule_score_and_error(snapshots):
    _, _, item = snapshots
    item = item.model_copy(deep=True)
    item.status = "score_only"
    item.report = None
    item.error = ErrorInfo(code="MODEL_TIMEOUT", message="模型调用超过单次时限")

    text = export_markdown(item)

    assert "仅规则评分" in text
    assert "总分：66.7 / 100" in text
    assert "AI 报告未生成" in text
    assert "规则评分仍然有效" in text
    assert "MODEL_TIMEOUT" in text


def test_failed_item_export_has_no_invented_score(snapshots):
    _, _, item = snapshots
    item = item.model_copy(deep=True)
    item.status = "failed"
    item.score_result = None
    item.report = None
    item.model_metadata = None
    item.error = ErrorInfo(code="INTERNAL_ERROR", message="任务处理失败")

    text = export_markdown(item)

    assert "没有可用的规则评分" in text
    assert "总分" not in text
    assert "INTERNAL_ERROR" in text


def test_partial_diagnosis_is_composed_from_per_item_sections(snapshots):
    _, _, item = snapshots
    succeeded = item.model_copy(deep=True)
    score_only = item.model_copy(deep=True)
    score_only.job = score_only.job.model_copy(update={"version": 2})
    score_only.status = "score_only"
    score_only.report = None
    score_only.error = ErrorInfo(code="PROVIDER_UNAVAILABLE", message="供应商暂时不可用")

    combined = export_markdown(succeeded) + export_markdown(score_only)

    assert "v1" in combined and "v2" in combined
    assert combined.count("总分：66.7 / 100") == 2
    assert "PROVIDER_UNAVAILABLE" in combined


def test_model_switch_changes_metadata_but_not_score(snapshots):
    _, _, item = snapshots
    switched = item.model_copy(deep=True)
    switched.model_metadata.model_id = "demo-model-b"
    switched.model_metadata.model = "synthetic-fake-v1"

    baseline = export_markdown(item)
    other = export_markdown(switched)

    assert "总分：66.7 / 100" in baseline and "总分：66.7 / 100" in other
    assert "模型选择：demo-model-a" in baseline
    assert "模型选择：demo-model-b" in other


def test_untrusted_text_is_html_escaped(snapshots):
    _, _, item = snapshots
    item = item.model_copy(deep=True)
    item.report.summary = "<script>alert(1)</script>"
    item.score_result.assessments[0].reason = '<img src=x onerror="alert(1)">'

    text = export_markdown(item)

    assert "<script>" not in text
    assert "<img" not in text
    assert "&lt;script&gt;" in text
    assert "&lt;img" in text


def test_export_is_deterministic(snapshots):
    _, _, item = snapshots
    assert export_markdown(copy.deepcopy(item)) == export_markdown(item)
