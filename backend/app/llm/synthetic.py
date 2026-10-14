"""M5 假网关的固定合成输出。

用途：让 C/B 在没有真实模型和密钥的情况下，通过统一网关拿到四类任务的结构化
结果（见 [02-architecture.md](../../../docs/02-architecture.md)「Mock 与集成」）。
全部内容为虚构，不含真实简历、JD 或供应商信息；这里只产出纯数据，不调用模型、
不读文件、不连数据库。

档案与岗位逐字沿用冻结样例 `docs/examples/profile.json`、`docs/examples/job.json`
与 M3 合成端口的同一套虚构素材（来源 ID `manual-revision-1`、同一原文与引用），
且本模块自带常量，不 import 其他模块的实现，避免模块间耦合；跨模块一致性由
`tests/llm/test_cross_module.py` 用例固定，漂移即失败。
"""

from collections.abc import Mapping
from typing import Any

SYNTHETIC_SOURCE_ID = "manual-revision-1"
SYNTHETIC_SOURCE_TEXT = (
    "使用 Python 完成课程数据清洗项目。\n了解 SQL 基本语法。\n已获得计算机相关专业本科学位。\n"
)
SYNTHETIC_JOB_RAW_TEXT = (
    "必须有 Python 项目应用经验。\n必须具备 SQL 应用能力。"
    "\n熟悉 Docker 优先。\n本科及以上学历优先。"
)
SYNTHETIC_ASSISTANT_MESSAGE = "这是合成数据的示例追问：这个项目里你具体负责哪一部分？"


def synthetic_profile_payload() -> dict[str, Any]:
    """与 docs/examples/profile.json 的 content 逐字一致的虚构档案。"""
    return {
        "overview": "完全虚构的课程演示档案。",
        "as_of_month": "2026-09",
        "facts": [
            {
                "id": "f1",
                "kind": "project",
                "label": "Python",
                "value": None,
                "polarity": "positive",
                "application": "applied",
                "start_month": None,
                "end_month": None,
                "completed": None,
                "evidence_ids": ["e1"],
            },
            {
                "id": "f2",
                "kind": "skill",
                "label": "SQL",
                "value": None,
                "polarity": "positive",
                "application": "claimed",
                "start_month": None,
                "end_month": None,
                "completed": None,
                "evidence_ids": ["e2"],
            },
            {
                "id": "f3",
                "kind": "education",
                "label": "计算机相关专业",
                "value": "bachelor",
                "polarity": "positive",
                "application": "claimed",
                "start_month": None,
                "end_month": None,
                "completed": True,
                "evidence_ids": ["e3"],
            },
        ],
        "evidence": [
            {
                "id": "e1",
                "source_type": "manual",
                "source_id": SYNTHETIC_SOURCE_ID,
                "quote": "使用 Python 完成课程数据清洗项目。",
                "locator": None,
            },
            {
                "id": "e2",
                "source_type": "manual",
                "source_id": SYNTHETIC_SOURCE_ID,
                "quote": "了解 SQL 基本语法。",
                "locator": None,
            },
            {
                "id": "e3",
                "source_type": "manual",
                "source_id": SYNTHETIC_SOURCE_ID,
                "quote": "已获得计算机相关专业本科学位。",
                "locator": None,
            },
        ],
    }


def synthetic_chat_payload() -> dict[str, Any]:
    """profile_chat 的输出：助手消息 + 档案草稿。"""
    return {
        "assistant_message": SYNTHETIC_ASSISTANT_MESSAGE,
        "profile_content": synthetic_profile_payload(),
    }


def synthetic_job_payload() -> dict[str, Any]:
    """与 docs/examples/job.json 的 content 一致的虚构岗位。"""
    return {
        "title": "数据开发课程演示岗位",
        "company_name": "虚构示例公司",
        "company_context": "仅用于测试，无真实招聘信息。",
        "requirements": [
            {
                "id": "r1",
                "quote": "必须有 Python 项目应用经验。",
                "category": "skill",
                "importance": "must",
                "operator": "has_skill",
                "target": "Python",
                "ignored": False,
                "ignore_reason": None,
                "subject": None,
            },
            {
                "id": "r2",
                "quote": "必须具备 SQL 应用能力。",
                "category": "skill",
                "importance": "must",
                "operator": "has_skill",
                "target": "SQL",
                "ignored": False,
                "ignore_reason": None,
                "subject": None,
            },
            {
                "id": "r3",
                "quote": "熟悉 Docker 优先。",
                "category": "skill",
                "importance": "preferred",
                "operator": "has_skill",
                "target": "Docker",
                "ignored": False,
                "ignore_reason": None,
                "subject": None,
            },
            {
                "id": "r4",
                "quote": "本科及以上学历优先。",
                "category": "education",
                "importance": "preferred",
                "operator": "degree_at_least",
                "target": "bachelor",
                "ignored": False,
                "ignore_reason": None,
                "subject": None,
            },
        ],
    }


# 评估状态到 gap 类型的对应关系（06-ai-contract.md：partial→partial_gap，unknown→needs_evidence）。
GAP_KIND_BY_STATUS = {
    "unmet": "explicit_gap",
    "partial": "partial_gap",
    "unknown": "needs_evidence",
}
_FOLLOW_UP = {
    "unmet": ("P0", "now"),
    "partial": ("P1", "next_2_weeks"),
    "unknown": ("P1", "next_2_weeks"),
}


def synthetic_report_payload(score_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """按评分明细生成一份「只解释、不改分」的合成报告。

    分数由 M4 决定；这里只根据 assessments 的既有状态派生 gaps/suggestions/actions，
    不引入分数以外的新结论，也不填看似真实的虚构数字。缺少评分明细时返回空报告，
    由调用方决定是否视为失败。
    """
    summary = "[演示数据] 假模型网关生成的合成报告；分数与结论以评分明细为准。"
    if not score_result:
        return {"summary": summary, "gaps": [], "suggestions": [], "actions": []}

    assessments = list(score_result.get("assessments") or [])
    gaps: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    for assessment in assessments:
        requirement_id = assessment.get("requirement_id")
        status = assessment.get("status")
        kind = GAP_KIND_BY_STATUS.get(status)
        if requirement_id is None or kind is None:
            continue
        evidence_ids = sorted(assessment.get("evidence_ids") or [])
        gaps.append(
            {
                "requirement_id": requirement_id,
                "kind": kind,
                "description": f"[演示数据] 要求 {requirement_id} 当前评估为 {status}。",
                # gap 的证据必须落在该条评估已有的引用之内。
                "evidence_ids": evidence_ids,
            }
        )
        if status in {"unmet", "partial"}:
            suggestions.append(
                {
                    "requirement_id": requirement_id,
                    "original": None,
                    "revised": "在[真实项目名称]中补充与该要求相关的[实际任务]与[可核实结果]。",
                    "rationale": "提供事实模板，仅在确实做过时补充，不照抄虚构成果。",
                    "evidence_ids": [],
                    "requires_user_input": True,
                }
            )
        priority, horizon = _FOLLOW_UP.get(status, ("P2", "next_2_months"))
        actions.append(
            {
                "requirement_id": requirement_id,
                "priority": priority,
                "horizon": horizon,
                "task": f"[演示数据] 补充要求 {requirement_id} 的可核实证据。",
                "done_when": "能提供一段可核实的原文或记录支撑该要求。",
            }
        )
    return {"summary": summary, "gaps": gaps, "suggestions": suggestions, "actions": actions}
