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
from decimal import Decimal

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

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_DIGIT_CHARS = "".join(_CN_DIGITS)
_CN_NUMERAL = re.compile(rf"[{_CN_DIGIT_CHARS}十百千万亿]+(?:点[{_CN_DIGIT_CHARS}]+)?[万亿]?")
_CN_PERCENT = re.compile(
    rf"百分之\s*([{_CN_DIGIT_CHARS}十百千万亿]+(?:点[{_CN_DIGIT_CHARS}]+)?|\d+(?:\.\d+)?)"
)
_ARABIC_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*([万亿])?\s*([%％])?")
# 分数后必须是分数单位、标点或行尾；“评分一致/评分一般”里的“一”不是分数。
_SCORE_CLAIM = re.compile(
    rf"(?:总分|得分|分数|评分)\s*(?:为|是|：|:)?\s*"
    rf"(\d+(?:\.\d+)?|[{_CN_DIGIT_CHARS}十百千万亿]+(?:点[{_CN_DIGIT_CHARS}]+)?)"
    rf"(?=\s*(?:分|[%％]|[/／]|[。，,；;！!?？（(]|$))"
)
_CN_QUANTITY_UNITS = (
    "个",
    "次",
    "项",
    "条",
    "份",
    "人",
    "位",
    "年",
    "月",
    "天",
    "日",
    "小时",
    "分钟",
    "秒",
    "倍",
    "元",
    "块",
    "万元",
    "亿元",
    "%",
    "％",
)


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
        claimed = round(float(_cn_value(match.group(1))), 1)
        if claimed != round(score, 1):
            _invalid("报告摘要写入了与评分明细不同的分数")


def _canonical(value: Decimal) -> str:
    value = value.normalize()
    if value == value.to_integral_value():
        return str(int(value))
    return format(value, "f").rstrip("0").rstrip(".")


def _cn_integer(text: str) -> int:
    if text in {"万", "亿"}:
        return 10_000 if text == "万" else 100_000_000
    # 二〇二五这类逐位写法没有十/百/千单位，必须按位拼接，不能只留最后一位。
    if not any(char in _CN_SMALL_UNITS or char in "万亿" for char in text):
        return int("".join(str(_CN_DIGITS[char]) for char in text))
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_SMALL_UNITS:
            if number == 0:
                number = 1
            section += number * _CN_SMALL_UNITS[char]
            number = 0
        elif char == "万":
            section += number
            total += section * 10_000
            section = 0
            number = 0
        elif char == "亿":
            section += number
            total = (total + section) * 100_000_000
            section = 0
            number = 0
    return total + section + number


def _cn_value(text: str) -> Decimal:
    if all(char.isdigit() or char == "." for char in text):
        return Decimal(text)
    if text in {"万", "亿"}:
        return Decimal(10_000 if text == "万" else 100_000_000)
    # 小数和万/亿后缀是一个整体：两点五万 = 2.5 × 10000，不能拆成 2.5 + 10000。
    if text.endswith(("万", "亿")):
        multiplier = Decimal(10_000 if text.endswith("万") else 100_000_000)
        return _cn_value(text[:-1]) * multiplier
    if "点" in text:
        whole, fraction = text.split("点", 1)
        value = Decimal(_cn_integer(whole or "零"))
        if fraction:
            value += Decimal("0." + "".join(str(_CN_DIGITS[char]) for char in fraction))
        return value
    return Decimal(_cn_integer(text))


def _is_quantity_claim(token: str, text: str, end: int) -> bool:
    """区分数量/比例和“一致”“一下”“万一”等普通词。"""
    following = text[end:]
    if token in {"十", "百", "千", "万", "亿"}:
        # 单个量级字只有后接单位时才视为数量，避免匹配“百分之”中的“百”。
        return following.startswith(_CN_QUANTITY_UNITS)
    if token in {"千万", "万分", "万万"} and following.startswith(
        ("不要", "不能", "不可", "别", "注意", "小心", "要", "感谢", "抱歉")
    ):
        # “千万不要”“万分感谢”是程度副词，不是数量。
        return False
    if "点" in token:
        return True
    if any(char in token for char in "十百千万亿"):
        return True
    if sum(char in _CN_DIGITS for char in token) >= 2:
        return True
    if following.startswith(("%", "％")):
        return True
    # “一年”“一倍”等明确单位即使数值为 1 也是成果声明；“一致/一下”没有单位，不会命中。
    return following.startswith(_CN_QUANTITY_UNITS)


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _numeric_claims(text: str) -> set[tuple[str, str]]:
    """提取数值并保留百分比/普通数量类型，返回可与证据对齐的规范值。"""
    claims: set[tuple[str, str]] = set()
    consumed: list[tuple[int, int]] = []
    for match in _ARABIC_NUMBER.finditer(text):
        # “百分之 50”由百分比分支处理，不能再同时记成普通数量。
        if text[: match.start()].rstrip().endswith("百分之"):
            continue
        value = Decimal(match.group(1))
        if match.group(2) == "万":
            value *= 10_000
        elif match.group(2) == "亿":
            value *= 100_000_000
        kind = "percent" if match.group(3) else "quantity"
        claims.add((kind, _canonical(value)))
        consumed.append(match.span())
    for match in _CN_PERCENT.finditer(text):
        claims.add(("percent", _canonical(_cn_value(match.group(1)))))
        consumed.append(match.span())
    for match in _CN_NUMERAL.finditer(text):
        # 已被阿拉伯数字+万/亿或“百分之…”消费的字符不再单独计数。
        if _overlaps(match.start(), match.end(), consumed):
            continue
        token = match.group(0)
        if _is_quantity_claim(token, text, match.end()):
            kind = "percent" if text[match.end() :].startswith(("%", "％")) else "quantity"
            claims.add((kind, _canonical(_cn_value(token))))
    return claims


def _check_suggestion_numbers(
    evidence_ids: list[str], revised: str, evidence: Mapping[str, Evidence]
) -> None:
    supported = {
        number
        for evidence_id in evidence_ids
        for number in _numeric_claims(evidence[evidence_id].quote)
    }
    # 方括号本身不能把具体数字洗成“占位符”，只有已知占位文本才被移除。
    uncovered = _numeric_claims(USER_FILL_PLACEHOLDER.sub("", revised))
    if uncovered - supported:
        _invalid("改写包含无证据支持的具体数字，请改用待填写占位符")
