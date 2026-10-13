"""M3 语义校验：把档案与 JD 内容验到「可以保存、可以评分」的程度。

这里只做纯校验与规范化：不访问数据库、不调用模型、不产生任何副作用。
「证据引用必须是来源原文的真实子串」这条规则需要原文，因此由调用方（M2）
把来源文本传进来，本模块不自己去读文件或消息。
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.contracts import Evidence, Fact, JobContent, ProfileContent, Requirement

from .errors import IntakeError

# 学历取值受控（03-database.md 数据字典）；degree_at_least 只能比较可排序的四档。
EDUCATION_VALUES = frozenset({"associate", "bachelor", "master", "doctorate", "other"})
DEGREE_TARGETS = frozenset({"associate", "bachelor", "master", "doctorate"})

# 只用 ASCII 数字，避免 int() 接受全角数字或其它 Unicode 数字。
_POSITIVE_INTEGER = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class ProfileValidation:
    """档案校验结果。warnings 供调用方提示用户，不阻断保存。"""

    content: ProfileContent
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobValidation:
    """岗位校验结果。content.requirements 已按规范化键去重。"""

    content: JobContent
    warnings: tuple[str, ...] = ()


def validate_profile_content(
    content: ProfileContent,
    sources: Mapping[str, str],
    *,
    today: date | None = None,
) -> ProfileValidation:
    """校验档案内容，返回可保存的结果。

    sources 是「来源 ID → 该来源的原文」，用于核对 evidence.quote。
    today 仅用于测试注入，默认取当天日期判断 as_of_month 是否来自未来。
    """
    reference_day = today or date.today()
    _require_as_of_month_not_future(content.as_of_month, reference_day)
    _require_unique_ids([fact.id for fact in content.facts], "事实")
    _require_unique_ids([item.id for item in content.evidence], "证据")

    known_evidence_ids = {item.id for item in content.evidence}
    for item in content.evidence:
        _require_quote_from_source(item, sources)

    for fact in content.facts:
        missing = [eid for eid in fact.evidence_ids if eid not in known_evidence_ids]
        if missing:
            raise IntakeError(
                "UNKNOWN_EVIDENCE_REFERENCE",
                f"事实 {fact.id} 引用了档案中不存在的证据：{', '.join(missing)}",
            )
        _require_month_range(fact)
        _require_education_value(fact)

    return ProfileValidation(content=content)


def validate_job_content(content: JobContent, raw_text: str) -> JobValidation:
    """校验岗位内容：引用来自 JD 原文、要求语义完整、重复要求合并。"""
    _require_unique_ids([item.id for item in content.requirements], "岗位要求")
    for requirement in content.requirements:
        if requirement.quote not in raw_text:
            raise IntakeError(
                "QUOTE_NOT_IN_SOURCE",
                f"要求 {requirement.id} 的引用不是 JD 原文的子串：{requirement.quote!r}",
            )
        _require_requirement_semantics(requirement)

    merged, warnings = _merge_duplicate_requirements(content.requirements)
    return JobValidation(
        content=content.model_copy(update={"requirements": merged}), warnings=warnings
    )


def _require_as_of_month_not_future(value: str, reference_day: date) -> None:
    current_month = f"{reference_day.year:04d}-{reference_day.month:02d}"
    if value > current_month:
        raise IntakeError(
            "AS_OF_MONTH_IN_FUTURE",
            f"档案的统计截止月 {value} 晚于当前月 {current_month}，请用户确认时点。",
        )


def _require_unique_ids(ids: Sequence[str], what: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in ids:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise IntakeError(
            "DUPLICATE_LOCAL_ID",
            f"{what}存在重复编号：{', '.join(sorted(duplicates))}",
        )


def _require_quote_from_source(item: Evidence, sources: Mapping[str, str]) -> None:
    source = sources.get(item.source_id)
    if source is None:
        raise IntakeError(
            "UNKNOWN_SOURCE",
            f"证据 {item.id} 的来源 {item.source_id} 不在本次输入中，无法核对原文。",
        )
    if item.quote not in source:
        raise IntakeError(
            "QUOTE_NOT_IN_SOURCE",
            f"证据 {item.id} 的引用不是来源原文的子串：{item.quote!r}",
        )


def _require_month_range(fact: Fact) -> None:
    # 区间为 [start_month, end_month)，两端相等表示零长度，暂按非法处理。
    # PR #44 评审指出：半开区间只说明月数的计数方式，同月完成的短项目仍可能有合法
    # 技能证据。此判断待与 A/B 明确「可保存事实」与「可累计月数」的录入规则后再定，
    # 本轮不作为阻塞项。
    if fact.start_month and fact.end_month and fact.start_month >= fact.end_month:
        raise IntakeError(
            "INVALID_MONTH_RANGE",
            f"事实 {fact.id} 的起止月份非法：{fact.start_month} → {fact.end_month}",
        )


def _require_education_value(fact: Fact) -> None:
    if fact.kind != "education" or fact.value is None:
        return
    if fact.value not in EDUCATION_VALUES:
        raise IntakeError(
            "INVALID_EDUCATION_VALUE",
            f"事实 {fact.id} 的学历取值 {fact.value!r} 不在允许集合 {sorted(EDUCATION_VALUES)} 内。",
        )


def _require_requirement_semantics(requirement: Requirement) -> None:
    if requirement.ignored and not (requirement.ignore_reason or "").strip():
        raise IntakeError(
            "MISSING_IGNORE_REASON",
            f"要求 {requirement.id} 标记为不计分，必须写明原因。",
        )

    if requirement.operator == "min_months":
        if not (requirement.subject or "").strip():
            raise IntakeError(
                "INVALID_SUBJECT",
                f"要求 {requirement.id} 的 operator 为 min_months，必须写明 subject（相关领域标签）。",
            )
        _require_positive_month_count(requirement)
        return

    # min_months 之外的 operator，subject 必须为 null（05-scoring.md）。
    # 这条通用约束独立于各 operator 的分支，避免学历等分支把它漏掉。
    if requirement.subject is not None:
        raise IntakeError(
            "INVALID_SUBJECT",
            f"要求 {requirement.id} 的 operator 为 {requirement.operator}，subject 必须为 null。",
        )

    if requirement.operator == "degree_at_least" and requirement.target not in DEGREE_TARGETS:
        raise IntakeError(
            "INVALID_DEGREE_TARGET",
            f"要求 {requirement.id} 的学历目标 {requirement.target!r} 不在 "
            f"{sorted(DEGREE_TARGETS)} 内。",
        )


def _require_positive_month_count(requirement: Requirement) -> None:
    """min_months 的 target 必须是正整数月数字符串。

    只接受 ASCII 数字；int() 对超长数字串会抛普通 ValueError（Python 有整数转换
    位数限制），这里一并转成带错误码的 IntakeError，调用方不必处理裸异常。
    """
    target = requirement.target
    months = 0
    if _POSITIVE_INTEGER.fullmatch(target):
        try:
            months = int(target)
        except ValueError:
            months = 0
    if months < 1:
        raise IntakeError(
            "INVALID_MIN_MONTHS_TARGET",
            f"要求 {requirement.id} 的 min_months 目标 {target!r} 必须是正整数月数。",
        )


def _requirement_key(requirement: Requirement) -> tuple[str, str, str, str, str]:
    """重复识别键：operator/target/subject/category 加原文，规范化后比较。

    原文一并入键，这样「接受在读」和「不接受在读」这类结构相同、限制不同的要求
    不会被当成同一条静默合并。
    """
    return (
        requirement.operator,
        requirement.target.strip().casefold(),
        (requirement.subject or "").strip().casefold(),
        requirement.category,
        requirement.quote.strip(),
    )


def _merge_duplicate_requirements(
    requirements: Sequence[Requirement],
) -> tuple[list[Requirement], tuple[str, ...]]:
    """合并完全重复的要求，保留首次出现的顺序；重要性冲突时保留 must 并提示确认。

    结构字段相同但原文不同的两条要求无法自动判断是否等价：静默丢弃会让分数随要求
    顺序变化，静默保留又会重复加权，因此抛 REQUIREMENT_CONFLICT 交用户确认后再合并。
    """
    merged: list[Requirement] = []
    positions: dict[tuple[str, str, str, str, str], int] = {}
    structural_positions: dict[tuple[str, str, str, str], int] = {}
    warnings: list[str] = []

    for requirement in requirements:
        key = _requirement_key(requirement)
        index = positions.get(key)
        if index is None:
            structural = key[:4]
            conflict_index = structural_positions.get(structural)
            if conflict_index is not None:
                other = merged[conflict_index]
                raise IntakeError(
                    "REQUIREMENT_CONFLICT",
                    f"要求 {other.id} 与 {requirement.id} 的 operator/target/subject/category "
                    f"相同但原文不同（{other.quote!r} / {requirement.quote!r}），"
                    "无法判断是否为同一条要求，请用户确认后再提交。",
                )
            positions[key] = len(merged)
            structural_positions[structural] = len(merged)
            merged.append(requirement)
            continue

        existing = merged[index]
        if existing.importance == "preferred" and requirement.importance == "must":
            merged[index] = requirement
        if existing.importance != requirement.importance:
            warnings.append(
                f"要求 {existing.id} 与 {requirement.id} 重复但重要性冲突，已按 must 计并要求用户确认。"
            )
        else:
            warnings.append(f"要求 {requirement.id} 与 {existing.id} 重复，已合并为一条。")

    return merged, tuple(warnings)
