"""Server-owned score narration; model advice never decides gaps or score scope."""

from pydantic import BaseModel, ConfigDict

from app.contracts import ReportContent, ScoreResult
from app.contracts.models import Action, Suggestion

from .validation import GAP_KIND_BY_STATUS


class ReportAdvice(BaseModel):
    """Private provider output; the public ReportContent contract stays unchanged."""

    model_config = ConfigDict(extra="forbid", strict=True)

    suggestions: list[Suggestion]
    actions: list[Action]


_UNKNOWN_TEXT = {
    "manual_review": "此项需人工结合已确认材料核对，不表示未提供相关信息或不具备相应能力。",
    "unsupported_condition": "当前规则无法自动判断此项条件，需人工核对，不作为能力缺失结论。",
    "conflicting_evidence": "相关记录存在冲突，需核对原文后由本人澄清。",
}


def explain_score(score: ScoreResult) -> dict:
    """Describe only stored statuses, without interpreting source text or filling facts."""
    summary = "本次诊断反映已确认材料对岗位要求的覆盖情况，不代表录用概率。"
    if any(not item.counted_in_score for item in score.assessments):
        summary += "评分仅覆盖规则可自动判断的要求，其余要求保留供人工核对。"
    gaps = []
    for item in score.assessments:
        if item.status == "met":
            continue
        if item.status == "unknown":
            description = _UNKNOWN_TEXT.get(
                item.unknown_reason,
                "规则尚未确认本项要求，请结合已确认材料和对应条件核对；"
                "这不表示原文没有记录或不具备相关能力。",
            )
        elif item.status == "partial":
            description = "现有证据只支持本项要求的部分覆盖，完整满足程度仍需结合原文核对。"
        else:
            description = "已确认记录未满足本项明确条件；具体条件和依据见评分明细。"
        gaps.append(
            {
                "requirement_id": item.requirement_id,
                "kind": GAP_KIND_BY_STATUS[item.status],
                "description": description,
                "evidence_ids": list(item.evidence_ids),
            }
        )
    return {"summary": summary, "gaps": gaps}


def assemble_report(advice: dict, score: ScoreResult) -> dict:
    return ReportContent(
        **explain_score(score), **ReportAdvice.model_validate(advice).model_dump(mode="json")
    ).model_dump(mode="json")
