"""Shared, bounded semantics for confirmed structured attributes and conditions."""

import json
import re

from app.contracts.models import Fact, Requirement

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


def explicit_graduation_quote(quotes: list[str], date_value: str) -> str | None:
    """Require a linked graduation event, or a cohort when only a year is needed."""
    year, *months = map(int, date_value.split("-"))
    month = r"(?:0?[1-9]|1[0-2])"
    if months:
        month = rf"0?{months[0]}" if months[0] < 10 else str(months[0])
    day = r"(?:0?[1-9]|[12][0-9]|3[01])"
    suffix = rf"(?:[-./]{month}(?:[-./]{day})?|年{month}月(?:{day}日)?)"
    date = rf"(?<!\d){year}{suffix if months else f'(?:{suffix}|年)?'}(?!\d)"
    before = re.compile(
        rf"(?:毕业|离校)(?:时间|日期|年份)?"
        rf"(?:(?:为|于|在|是|定于|预计|预期|计划)|[:：])*{date}"
        r"(?:[（(](?:预计|预期)[)）])?(?=$|[)）])"
    )
    after = re.compile(
        rf"{date}[（(]?(?:预计|预期|计划)?(?:专科|大专|本科|学士|硕士|博士)?(?:毕业|离校)"
        r"(?:[（(](?:预计|预期|计划)[)）])?(?=$|[)）]|于|后|并|且)"
    )
    cohort = re.compile(rf"(?<!\d){year}届") if not months else None
    month_names = (
        "jan(?:uary)?",
        "feb(?:ruary)?",
        "mar(?:ch)?",
        "apr(?:il)?",
        "may",
        "jun(?:e)?",
        "jul(?:y)?",
        "aug(?:ust)?",
        "sep(?:t(?:ember)?)?",
        "oct(?:ober)?",
        "nov(?:ember)?",
        "dec(?:ember)?",
    )
    named_month = month_names[months[0] - 1] if months else "|".join(month_names)
    english_date = rf"(?:{date}|(?:{named_month})\.?{year}(?!\d))"
    english = re.compile(
        rf"(?:graduation(?:date|year)?|graduat(?:e|ed|ing))"
        rf"(?:expected|in|on|is|:)*{english_date}(?=$|[)）])"
    )
    english_cohort = re.compile(rf"classof{year}(?!\d)") if not months else None
    candidates = []
    for quote in quotes:
        compact = "".join(quote.split()).casefold()
        # Read the whole linked evidence too: a shorter attribute quote must not
        # hide a denial, conditional or later postponement in that same record.
        if "离校" in compact and re.search(r"退学|休学|肄业", compact):
            return None
        for raw_clause in re.split(r"[，,。；;！？!?\n]", quote):
            clause = "".join(raw_clause.split()).casefold()
            related = re.search(r"毕业|离校|届|graduat|classof", clause)
            if related and (
                re.search(
                    r"待定|待确认|尚未确定|未确定|未定|未明确|不确定|不一定|无法确定|未提供|未知|另行通知|"
                    r"原计划|原定|不是|并非|不能|无法|未能|不会|延期|延后|推迟|如果|假如|假设|退学|休学|肄业|结业|^若",
                    clause,
                )
                or re.search(rf"(?:不属于|不属|非){year}届", clause)
                or re.search(
                    r"\b(?:not|no|never|unknown|uncertain|tbd|undecided|postponed|delayed|if|unless|withdrawn)\b",
                    raw_clause,
                    re.I,
                )
            ):
                return None
            # A standalone correction refers back to the stated schedule;
            # unrelated clauses such as 'GPA 未提供' or '实习延期' do not.
            if re.fullmatch(
                r"(?:但|但是|不过|然而)?(?:现已|目前|实际|已经|已|现|仍|还)?(?:具体时间|具体日期|时间|日期)?"
                r"(?:延期|延后|推迟|待定|待确认|尚未确定|未确定|不确定)(?:(?:到|至).+)?"
                r"|(?:but|however)?(?:now|already)?(?:postponed|delayed|undecided|uncertain|tbd)",
                clause,
            ):
                return None
            # Leaving after normal course completion is a supported expression;
            # a leave of absence/withdrawal or an undated course end is not.
            if "离校" in clause and not re.search(
                r"课程结束|完成课程|完成学业|学业完成|学业结束", compact
            ):
                continue
            if (
                before.search(clause)
                or after.search(clause)
                or cohort is not None
                and cohort.search(clause)
                or english.search(clause)
                or english_cohort is not None
                and english_cohort.search(clause)
            ):
                candidates.append(quote)
    return candidates[0] if candidates else None


def validate_attributes(
    fact: Fact,
    quotes: list[str],
    *,
    allow_education_status_conflict: bool = False,
    require_graduation_context: bool = True,
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
            linked = [quote for quote in quotes if attribute.quote in quote]
            if (
                explicit_graduation_quote([attribute.quote], attribute.value) is None
                or explicit_graduation_quote(linked, attribute.value) is None
            ):
                raise ValueError("毕业年份必须由原文中明确关联该年份的毕业表述或届别支持")
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
