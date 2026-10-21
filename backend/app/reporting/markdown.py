"""DiagnosisItem 的确定性 Markdown 导出。

M2 的导出路由负责会话归属、HTTP 头和诊断级拼接；本模块只把单个岗位结果
渲染成 UTF-8 Markdown。同一份 DiagnosisItem 无论刷新页面还是按 URL 重新读取，
都得到同样的文本（T23）。

安全边界：简历、岗位和模型输出都是不可信数据。所有字段在写入 Markdown 前做
HTML 转义，输出不携带可执行 HTML；这里也不插入任何链接或图片语法。
"""

from html import escape

from app.contracts import DiagnosisItem

STATUS_LABELS = {
    "pending": "等待处理",
    "scoring": "评分中",
    "reporting": "生成报告中",
    "succeeded": "完成",
    "score_only": "仅规则评分（AI 报告未生成）",
    "failed": "失败",
}
GAP_LABELS = {
    "explicit_gap": "明确差距",
    "partial_gap": "部分差距",
    "needs_evidence": "待补充证据",
}
ASSESSMENT_LABELS = {
    "met": "满足",
    "partial": "部分满足",
    "unmet": "不满足",
    "unknown": "证据不足",
}
PRIORITY_LABELS = {"P0": "P0（优先）", "P1": "P1", "P2": "P2（可稍后）"}
HORIZON_LABELS = {
    "now": "现在",
    "next_2_weeks": "两周内",
    "next_2_months": "两个月内",
}


def _inline(value: object) -> str:
    """单行字段：转义 HTML、折叠换行，避免破坏 Markdown 结构。"""
    return escape(str(value), quote=False).replace("\r", " ").replace("\n", " ").strip()


def _block(value: object) -> str:
    """多行字段：保留换行，但每一行都做 HTML 转义。"""
    return escape(str(value), quote=False).replace("\r\n", "\n").replace("\r", "\n").strip()


def export_markdown(item: DiagnosisItem) -> str:
    """渲染一个岗位的结果；成功、score_only、失败与处理中状态都可导出。"""
    lines: list[str] = [
        f"## 岗位 {_inline(item.job.id)} / v{_inline(item.job.version)}",
        "",
        f"- 结果状态：{STATUS_LABELS.get(item.status, _inline(item.status))}",
        "",
    ]

    lines.extend(_score_section(item))
    lines.extend(_report_section(item))
    lines.extend(_error_section(item))
    lines.extend(_metadata_section(item))

    return "\n".join(lines).rstrip() + "\n"


def _score_section(item: DiagnosisItem) -> list[str]:
    lines = ["### 规则评分（由 M4 计算，报告不可修改）", ""]
    score = item.score_result
    if score is None:
        lines.extend(["本岗位没有可用的规则评分。", ""])
        return lines

    lines.extend(
        [
            f"- 总分：{score.score} / 100",
            f"- 未知权重比例：{score.unknown_weight_ratio}",
            f"- 评分规则：{_inline(score.rule_version)}",
            f"- 匹配版本：{_inline(score.matcher_version)}",
            "",
        ]
    )
    if score.dimensions:
        lines.append("类别分数：")
        lines.extend(
            f"- {_inline(dimension.category)}：{dimension.score}" for dimension in score.dimensions
        )
        lines.append("")

    lines.append("评分明细：")
    lines.append("")
    for assessment in score.assessments:
        evidence = "、".join(_inline(value) for value in assessment.evidence_ids) or "无"
        lines.append(
            f"- {_inline(assessment.requirement_id)}："
            f"{ASSESSMENT_LABELS.get(assessment.status, _inline(assessment.status))}"
            f"；类别 {_inline(assessment.category)}"
            f"；重要性 {_inline(assessment.importance)}"
            f"；权重 {assessment.weight}"
            f"；系数 {assessment.coefficient}"
            f"；证据 {evidence}"
        )
        lines.append(f"  - 理由：{_inline(assessment.reason)}")
    lines.append("")
    return lines


def _report_section(item: DiagnosisItem) -> list[str]:
    lines = ["### AI 报告（只解释评分，不改分）", ""]
    if item.report is not None:
        lines.extend([_block(item.report.summary), ""])

        if item.report.gaps:
            lines.append("差距：")
            for gap in item.report.gaps:
                evidence = "、".join(_inline(value) for value in gap.evidence_ids) or "无"
                kind = GAP_LABELS.get(gap.kind, _inline(gap.kind))
                lines.append(
                    f"- {_inline(gap.requirement_id)}（{kind}）：{_inline(gap.description)}"
                )
                lines.append(f"  - 证据：{evidence}")
            lines.append("")

        if item.report.suggestions:
            lines.append("改写建议：")
            for suggestion in item.report.suggestions:
                original = (
                    "无原文（需用户补充）"
                    if suggestion.original is None
                    else _inline(suggestion.original)
                )
                evidence = "、".join(_inline(value) for value in suggestion.evidence_ids) or "无"
                need_input = "是" if suggestion.requires_user_input else "否"
                lines.append(f"- 要求 {_inline(suggestion.requirement_id)}：")
                lines.append(f"  - 原文：{original}")
                lines.append(f"  - 建议表述：{_inline(suggestion.revised)}")
                lines.append(f"  - 理由：{_inline(suggestion.rationale)}")
                lines.append(f"  - 证据：{evidence}")
                lines.append(f"  - 需要用户补充：{need_input}")
            lines.append("")

        if item.report.actions:
            lines.append("下一步行动：")
            for action in item.report.actions:
                priority = PRIORITY_LABELS.get(action.priority, _inline(action.priority))
                horizon = HORIZON_LABELS.get(action.horizon, _inline(action.horizon))
                lines.append(
                    f"- {_inline(action.requirement_id)}（{priority}，{horizon}）："
                    f"{_inline(action.task)}"
                )
                lines.append(f"  - 完成标准：{_inline(action.done_when)}")
            lines.append("")
        return lines

    if item.status == "score_only":
        lines.extend(
            [
                "AI 报告未生成，本岗位已降级为仅规则评分。",
                "上方规则评分仍然有效，可正常查看和导出。",
                "",
            ]
        )
    elif item.status == "failed":
        lines.extend(["本岗位未生成 AI 报告。", ""])
    else:
        lines.extend(["AI 报告尚未生成。", ""])
    return lines


def _error_section(item: DiagnosisItem) -> list[str]:
    if item.error is None:
        return []
    lines = ["### 错误", "", f"- 错误码：{_inline(item.error.code)}"]
    if item.error.message:
        lines.append(f"- 说明：{_inline(item.error.message)}")
    lines.append("")
    return lines


def _metadata_section(item: DiagnosisItem) -> list[str]:
    metadata = item.model_metadata
    if metadata is None:
        return []
    lines = ["### 模型与版本", ""]
    lines.append(f"- 模型选择：{_inline(metadata.model_id)}")
    lines.append(f"- 供应商：{_inline(metadata.provider)}")
    lines.append(f"- 实际模型：{_inline(metadata.model)}")
    lines.append(f"- 提示版本：{_inline(metadata.prompt_version)}")
    lines.append(f"- 网关配置版本：{_inline(metadata.gateway_config_version)}")
    lines.append(f"- 生成时间：{_inline(metadata.generated_at)}")
    if metadata.provider == "fake":
        lines.append("")
        lines.append("注意：本报告由演示假模型生成，不代表真实诊断结论。")
    lines.append("")
    return lines
