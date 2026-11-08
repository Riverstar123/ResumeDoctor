"""Shared, bounded semantics for confirmed structured attributes and conditions."""

import json
import re

from app.contracts.models import Evidence, Fact, Requirement
from app.graduation_evidence import graduation_attribute_supported, source_contexts

ATTRIBUTE_KINDS = {
    "institution": {"education"},
    "major": {"education"},
    "graduation_year": {"education"},
    "enrollment": {"education"},
    "experience_type": {"experience"},
    "experience_domain": {"experience", "project"},
    "credential_status": {"credential"},
    "credential_level": {"credential"},
    "availability_days": {"availability"},
    "availability_months": {"availability"},
    "availability_start": {"availability"},
    "full_time": {"availability"},
}
NUMERIC_FIELDS = {
    "graduation_year": (1900, 2200),
    "availability_days": (0, 7),
    "availability_months": (0, 600),
}
ENUM_FIELDS = {
    "enrollment": {"enrolled", "completed"},
    "experience_type": {"internship", "employment", "volunteer"},
    "credential_status": {"partial", "complete", "preparing", "expired"},
    "full_time": {"true", "false"},
}


def valid_value(field: str, value: str) -> bool:
    if field in NUMERIC_FIELDS:
        low, high = NUMERIC_FIELDS[field]
        return bool(re.fullmatch(r"[0-9]{1,4}", value)) and low <= int(value) <= high
    if field in ENUM_FIELDS:
        return value in ENUM_FIELDS[field]
    if field == "availability_start":
        return value == "immediate" or bool(re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value))
    return bool(value.strip())


def education_status_conflict(fact: Fact) -> bool:
    """Check one education record; independent degrees may have different states."""
    if fact.kind != "education":
        return False
    states = {a.value for a in fact.attributes if a.name == "enrollment"}
    return (
        len(states) > 1
        or fact.completed is True
        and "enrolled" in states
        or fact.completed is False
        and "completed" in states
    )


_WAIT_COUNT = r"(?:[0-9一二两三四五六七八九十半]+|one|two|three|four|five|six|a|an)"
_ARRIVAL_DELAY = re.compile(
    rf"{_WAIT_COUNT}(?:个)?(?:工作日|天|周|星期|月)(?:内|后)?(?:到岗|入职|开始工作)"
)
_NOTICE_PERIOD = re.compile(
    rf"(?:with|after|in|subject\s+to)\s+{_WAIT_COUNT}\s+(?:working\s+)?(?:days?|weeks?|months?)(?:\s+notice)?(?=[.!。]|$)",
    re.I,
)


_WEEKLY_FREQUENCY = re.compile(
    rf"每(?:周|星期|礼拜)(?:可(?:以)?|能)?(?:至少|最多)?{_WAIT_COUNT}"
    rf"(?:[-—~～至到]{_WAIT_COUNT})?天(?:到岗|入职|开始工作)"
)
_IMMEDIATE = re.compile(
    r"(?:立即|马上|即刻|随时|尽快)(?:可以|可|能够|能)?(?:到岗|入职|开始(?:工作)?)"
    r"|\b(?:available|start)\s+immediately\b|\bas soon as possible\b",
    re.I,
)
_ARRIVAL_NEGATION = re.compile(
    r"(?:不能|不会|无法|不可|不可以|并非|尚未|不支持|不保证|未确认|待确认)(?:现在|目前|还|仍|可|能)?$"
    r"|\b(?:not|cannot|can't|unable(?: to)?|unconfirmed)(?:\s+currently)?\s*$",
    re.I,
)
_ARRIVAL_QUALIFIER = re.compile(
    r"(?:实际|目前|已经|仍然|具体|确切|时间|日期|安排|暂时|现|已|仍|还|尚|暂)*"
    r"(?:未(?:能|经)?确认|未确定|待确认|待定|不确定|延期|延后|推迟)"
    r"|(?:(?:actually|now|already|the|date|schedule|has|have|been|is|was|still)\s+)*"
    r"(?:delayed|postponed|unconfirmed|undecided|uncertain|tbd|not\s+(?:yet\s+)?(?:confirmed|determined))",
    re.I,
)


def _immediate_supported(
    quotes: list[str], attribute_quote: str, evidence: list[Evidence] | None
) -> bool:
    for quote in quotes:
        # Mask only a complete weekly-frequency span, never a separate wait.
        compact = re.sub(r"\s+", "", quote)
        without_frequency = _WEEKLY_FREQUENCY.sub("", compact)
        if _ARRIVAL_DELAY.search(without_frequency) or _NOTICE_PERIOD.search(quote):
            return False
    contexts = source_contexts(evidence) if evidence is not None else quotes
    for context in contexts:
        previous_event = False
        leading_uncertainty = False
        clauses = [
            part.strip(" .")
            for part in re.split(
                r"[，,。；;！？!?\n]|但是|但|不过|然而|\b(?:but|however)\b", context, flags=re.I
            )
            if part.strip(" .")
        ]
        for index, clause in enumerate(clauses):
            uncertain = bool(_ARRIVAL_QUALIFIER.fullmatch(clause))
            if uncertain and previous_event:
                return False
            if uncertain and index == 0:
                leading_uncertainty = True
            events = list(_IMMEDIATE.finditer(clause))
            for event in events:
                if leading_uncertainty or _ARRIVAL_NEGATION.search(clause[: event.start()]):
                    return False
            previous_event = bool(events)
    return any(attribute_quote in quote and _IMMEDIATE.search(quote) for quote in quotes)


def validate_attributes(
    fact: Fact,
    quotes: list[str],
    *,
    allow_education_status_conflict: bool = False,
    require_graduation_context: bool = True,
    require_availability_context: bool = True,
    evidence: list[Evidence] | None = None,
) -> None:
    seen = set()
    for attribute in fact.attributes:
        if fact.kind not in ATTRIBUTE_KINDS[attribute.name]:
            raise ValueError("属性类别与事实类别不一致")
        if not valid_value(attribute.name, attribute.value):
            raise ValueError("结构化属性值不合法")
        if not any(attribute.quote in quote for quote in quotes):
            raise ValueError("结构化属性引用必须来自该事实关联的原文证据")
        if attribute.name == "graduation_year" and require_graduation_context:
            if not graduation_attribute_supported(
                attribute.quote, attribute.value, quotes, degree=fact.value, evidence=evidence
            ):
                raise ValueError("毕业年份必须由原文中明确关联该年份的毕业表述或届别支持")
        if (
            require_availability_context
            and attribute.name == "availability_start"
            and attribute.value == "immediate"
            and not _immediate_supported(quotes, attribute.quote, evidence)
        ):
            raise ValueError(
                "立即到岗必须由关联原文明确支持，且不能存在延后到岗或通知期；不确定时保留原文并省略该属性"
            )
        if attribute.name == "availability_start" and attribute.value != "immediate":
            year, month = map(int, attribute.value.split("-"))
            explicit = re.search(rf"(?<!\d){year}\s*[-./年]\s*0?{month}(?!\d)", attribute.quote)
            if explicit is None:
                raise ValueError("到岗月份必须由原文明示年月支持，不能从暑期或其他相对时间猜测月份")
        key = (attribute.name, attribute.value)
        if key in seen:
            raise ValueError("结构化属性重复")
        seen.add(key)
    if not allow_education_status_conflict and education_status_conflict(fact):
        raise ValueError("学历完成状态与在读属性矛盾，请核对关联字段后保存")


def validate_condition(requirement: Requirement) -> None:
    if (requirement.operator == "criteria") != (requirement.condition is not None):
        raise ValueError("组合条件仅用于 criteria，且不能为空")
    if requirement.condition is None:
        return
    for group in requirement.condition.any_of:
        if group.scope == "same_fact":
            kinds = [
                ATTRIBUTE_KINDS.get(
                    c.field,
                    {"credential"}
                    if c.field == "credential"
                    else {"skill", "project", "experience"}
                    if c.field == "skill"
                    else set(),
                )
                for c in group.all_of
            ]
            if not set.intersection(*kinds):
                raise ValueError("同一事实条件必须适用于至少一种共同事实类别")
        for criterion in group.all_of:
            if criterion.quote not in requirement.quote:
                raise ValueError("子条件引用必须是本项 JD 原文的连续片段")
            field, comparison = criterion.field, criterion.comparison
            allowed = {"eq", "exists"}
            if field in NUMERIC_FIELDS or field == "availability_start":
                allowed |= {"gte", "lte"}
            if field == "credential":
                allowed = {"any_pass", "complete"}
            if field in {"skill", "manual"}:
                allowed = {"eq"}
            if comparison not in allowed:
                raise ValueError("条件比较方式不适用于该字段")
            if comparison != "exists" and not valid_value(field, criterion.value):
                raise ValueError("条件目标值不合法")
            if (
                field == "availability_start"
                and criterion.value == "immediate"
                and comparison != "eq"
            ):
                raise ValueError("尽快到岗只能比较明确的 immediate 承诺")


def condition_key(requirement: Requirement) -> str:
    """Order and explanatory titles/quotes cannot create a second weighted condition."""
    if requirement.condition is None:
        return ""
    branches = {
        (
            group.scope,
            tuple(
                sorted(
                    {
                        (c.field, c.comparison, " ".join(c.value.casefold().split()))
                        for c in group.all_of
                    }
                )
            ),
        )
        for group in requirement.condition.any_of
    }
    return json.dumps(sorted(branches), ensure_ascii=False)
