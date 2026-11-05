"""Safe output rejection categories; never include provider output or user text."""

OUTPUT_REASONS = frozenset(
    {
        "JSON_INVALID",
        "SCHEMA_INVALID",
        "OUTPUT_TRUNCATED",
        "UNSUPPORTED_NUMBERS",
        "REFERENCE_INVALID",
        "REPORT_VALIDATION_FAILED",
        "PROFILE_DATE_INVALID",
        "FUTURE_END_DATE",
    }
)

REPAIR_HINTS = {
    "OUTPUT_TRUNCATED": "上一次输出达到长度限制而被截断。精简措辞，完整保留所有必需字段和证据约束。",
    "UNSUPPORTED_NUMBERS": (
        "改写包含本条 evidence_ids 的原文不支持的数字或日期。"
        "删除这些数字/日期或改用 [请填写真实数据]；不得借用其他证据或 JD 的数字。"
        "中文数量词如‘一个’也属于数字；没有原文依据就使用不含数量的表述。"
    ),
    "REFERENCE_INVALID": (
        "gap.evidence_ids 只能复制对应 requirement_id 的评分明细 evidence_ids，"
        "不能引用该条评分之外的事实证据；评分明细无证据时用空数组。"
    ),
    "REPORT_VALIDATION_FAILED": (
        "报告未通过业务校验。逐项核对 gap 类型、必答缺口、原文引用、"
        "requires_user_input 和固定评分；不得改分或编造事实。"
    ),
}
