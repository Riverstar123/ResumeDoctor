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


def validate_attributes(fact: Fact, quotes: list[str]) -> None:
    seen = set()
    for attribute in fact.attributes:
        if fact.kind not in ATTRIBUTE_KINDS[attribute.name]:
            raise ValueError("属性类别与事实类别不一致")
        if not valid_value(attribute.name, attribute.value):
            raise ValueError("结构化属性值不合法")
        if not any(attribute.quote in quote for quote in quotes):
            raise ValueError("结构化属性引用必须来自该事实关联的原文证据")
        if attribute.name == "availability_start" and attribute.value != "immediate":
            year, month = map(int, attribute.value.split("-"))
            explicit = re.search(rf"(?<!\d){year}\s*[-./年]\s*0?{month}(?!\d)", attribute.quote)
            if explicit is None:
                raise ValueError("到岗月份必须由原文明示年月支持，不能从暑期或其他相对时间猜测月份")
        key = (attribute.name, attribute.value)
        if key in seen:
            raise ValueError("结构化属性重复")
        seen.add(key)


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
