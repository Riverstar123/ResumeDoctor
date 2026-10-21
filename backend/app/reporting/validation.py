"""报告语义校验：引用、gap 状态、分数不可改写与数字证据。

网关只保证 JSON 结构符合 ReportContent。这里再按 docs/06-ai-contract.md
「报告结构」和 docs/05-scoring.md「四种状态」核对业务语义：

- 所有 requirement_id 必须来自同一份冻结 ScoreResult，不能引用别的岗位；
- 所有 evidence_ids 必须来自同一份冻结档案，且 gap 证据是该条评分的子集；
- gap.kind 必须与评分状态一一对应，必答（must）未达标项不得遗漏；
- met 不得生成 gap；
- 建议中的具体数字必须有引用证据支撑，否则必须使用待填写占位符并
  requires_user_input=true（T18）；
- 报告没有可修改的 score 字段，摘要也不得声称不同分数。
"""

import re
from collections.abc import Mapping

from app.contracts import (
    Evidence,
    JobContent,
    ProfileContent,
    ReportContent,
    RequirementAssessment,
    ScoreResult,
)

from .errors import ReportError

GAP_KIND_BY_STATUS = {
    "unmet": "explicit_gap",
    "partial": "partial_gap",
    "unknown": "needs_evidence",
}
USER_FILL_PLACEHOLDER = re.compile(r"\[(?:请填写真实数据|真实项目名称|实际任务|可核实结果)\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?%?")
_SCORE_CLAIM = re.compile(r"(?:总分|得分|分数|评分)\s*(?:为|是|：|:)?\s*(\d+(?:\.\d+)?)")


def _invalid(message: str) -> None:
    raise ReportError("MODEL_OUTPUT_INVALID", message)


def validate_report(
    report: ReportContent,
    profile_content: ProfileContent,
    job_content: JobContent,
    score_result: ScoreResult,
    *,
    redacted_evidence: Mapping[str, str] | None = None,
) -> None:
    """校验报告与冻结快照/评分一致；不合格时抛 ReportError。"""
    evidence = {item.id: item for item in profile_content.evidence}
    requirements = {item.id: item for item in job_content.requirements if not item.ignored}
    assessments: dict[str, RequirementAssessment] = {}
    for assessment in score_result.assessments:
        if assessment.requirement_id in assessments:
            _invalid("评分明细包含重复要求")
        assessments[assessment.requirement_id] = assessment
    if set(assessments) != set(requirements):
        _invalid("评分明细与岗位可评分要求不一致")
    for assessment in score_result.assessments:
        if not set(assessment.evidence_ids) <= set(evidence):
            _invalid("评分明细引用了档案中不存在的证据")

    if not report.summary.strip():
        _invalid("报告摘要为空")
    _check_summary_score(report.summary, score_result.score)

    allowed_original = {item.quote for item in profile_content.evidence}
    if redacted_evidence:
        allowed_original.update(redacted_evidence.values())

    seen_gaps: set[str] = set()
    for gap in report.gaps:
        if gap.requirement_id not in assessments:
            _invalid("gap 引用了未评分要求")
        assessment = assessments[gap.requirement_id]
        if assessment.status == "met":
            _invalid("met 要求不得生成 gap")
        expected_kind = GAP_KIND_BY_STATUS.get(assessment.status)
        if expected_kind is None or gap.kind != expected_kind:
            _invalid("gap 类型与评分状态不一致")
        if not set(gap.evidence_ids) <= set(assessment.evidence_ids):
            _invalid("gap 证据超出该条评分明细")
        if gap.requirement_id in seen_gaps:
            _invalid("gap 重复")
        if not gap.description.strip():
            _invalid("gap 描述为空")
        seen_gaps.add(gap.requirement_id)

    mandatory_gaps = {
        assessment.requirement_id
        for assessment in score_result.assessments
        if assessment.importance == "must" and assessment.status != "met"
    }
    if mandatory_gaps - seen_gaps:
        _invalid("缺少必答要求的 gap")

    for suggestion in report.suggestions:
        if suggestion.requirement_id not in assessments:
            _invalid("建议引用了未评分要求")
        if not set(suggestion.evidence_ids) <= set(evidence):
            _invalid("建议引用了档案中不存在的证据")
        if not suggestion.revised.strip() or not suggestion.rationale.strip():
            _invalid("建议的 revised 或 rationale 为空")
        if suggestion.original is not None:
            if not suggestion.original.strip():
                _invalid("建议 original 为空字符串")
            if not any(suggestion.original in quote for quote in allowed_original):
                _invalid("建议原文不是用户证据的逐字片段")
        if USER_FILL_PLACEHOLDER.search(suggestion.revised) and (
            not suggestion.requires_user_input
        ):
            _invalid("待填写占位符必须要求用户输入")
        if (not suggestion.evidence_ids or suggestion.original is None) and (
            not suggestion.requires_user_input
        ):
            _invalid("缺少证据或原文的改写必须要求用户输入")
        _check_suggestion_numbers(suggestion.evidence_ids, suggestion.revised, evidence)

    for action in report.actions:
        if action.requirement_id not in assessments:
            _invalid("行动引用了未评分要求")
        if not action.task.strip() or not action.done_when.strip():
            _invalid("行动的 task 或 done_when 为空")


def _check_summary_score(summary: str, score: float) -> None:
    for match in _SCORE_CLAIM.finditer(summary):
        claimed = round(float(match.group(1)), 1)
        if claimed != round(score, 1):
            _invalid("报告摘要写入了与评分明细不同的分数")


def _check_suggestion_numbers(
    evidence_ids: list[str], revised: str, evidence: Mapping[str, Evidence]
) -> None:
    supported = {
        number
        for evidence_id in evidence_ids
        for number in _NUMBER.findall(evidence[evidence_id].quote)
    }
    # 方括号本身不能把具体数字洗成“占位符”，只有已知占位文本才被移除。
    uncovered = _NUMBER.findall(USER_FILL_PLACEHOLDER.sub("", revised))
    if set(uncovered) - supported:
        _invalid("改写包含无证据支持的具体数字，请改用待填写占位符")
