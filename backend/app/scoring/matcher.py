"""matcher-v1 over confirmed structured facts. No I/O, inference or wall clock."""

import re
from dataclasses import dataclass
from typing import Literal

from app.contracts import Fact, JobContent, ProfileContent, Requirement, RequirementAssessment

from .calculator import COEFFICIENTS, MATCHER_VERSION, WEIGHTS
from .errors import ScoringError
from .vocabulary import DEGREES, normalized_degree, normalized_label

Status = Literal["met", "partial", "unmet", "unknown"]
_PERSONAL_LABELS = {
    "age",
    "gender",
    "sex",
    "photo",
    "marital status",
    "birthplace",
    "户籍",
    "籍贯",
    "年龄",
    "性别",
    "照片",
    "婚育",
    "婚姻状况",
}
_PERSONAL_QUOTE = re.compile(
    r"(?:年龄|性别|籍贯|户籍|婚育|婚姻状况)\s*(?:要求|限制|不限|[:：<>=≤≥0-9]|为|男|女)"
    r"|(?:个人|本人|证件|简历|附|提供|上传).{0,4}照片"
)


@dataclass(frozen=True)
class PreparedJob:
    content: JobContent
    warnings: tuple[str, ...]
    merged_ids: dict[str, tuple[str, ...]]
    requires_confirmation: bool


def _key(requirement: Requirement) -> tuple[str, str, str | None, str]:
    target = normalized_label(requirement.target)
    if requirement.operator == "degree_at_least":
        target = normalized_degree(requirement.target)
    elif requirement.operator == "min_months" and re.fullmatch(r"[0-9]+", target):
        target = str(int(target))
    subject = normalized_label(requirement.subject) if requirement.subject is not None else None
    return requirement.operator, target, subject, requirement.category


def _enrollment_policy(quote: str) -> Literal["accept", "reject", "unspecified", "conflict"]:
    """Use the same bounded condition parser in matching and pre-dedup checks."""
    text = quote.casefold()
    negative_phrases = (
        "不接受在读",
        "不允许在读",
        "不包括在读",
        "不含在读",
        "在读不可",
        "不考虑在读",
        "not currently enrolled accepted",
    )
    rejected = any(phrase in text for phrase in negative_phrases)
    # An acceptance substring inside a negation is not a second positive clause.
    for phrase in negative_phrases:
        text = text.replace(phrase, "")
    accepted = any(
        phrase in text
        for phrase in (
            "接受在读",
            "允许在读",
            "包括在读",
            "含在读",
            "在读可",
            "在读亦可",
            "currently enrolled accepted",
        )
    )
    if accepted and rejected:
        return "conflict"
    if rejected:
        return "reject"
    return "accept" if accepted else "unspecified"


def prepare_job(job_content: JobContent) -> PreparedJob:
    """Pre-confirmation helper: deduplicate and expose all decisions for C/the user.

    Importance conflicts choose must in the returned draft, but cannot be scored
    implicitly: assess_requirements rejects them until the new draft is confirmed.
    """
    job = JobContent.model_validate(job_content.model_dump())
    ids = [requirement.id for requirement in job.requirements]
    if len(ids) != len(set(ids)):
        raise ScoringError("INVALID_SCORING_INPUT", "岗位要求 ID 必须唯一。")
    groups: dict[tuple, list[Requirement]] = {}
    ignored = []
    warnings = []
    merged_ids = {}
    requires_confirmation = False
    for requirement in job.requirements:
        personal = (
            normalized_label(requirement.target) in _PERSONAL_LABELS
            or normalized_label(requirement.subject or "") in _PERSONAL_LABELS
            or bool(_PERSONAL_QUOTE.search(requirement.quote))
        )
        if personal and not requirement.ignored:
            requirement = requirement.model_copy(
                update={"ignored": True, "ignore_reason": "个人属性不参与 coverage-v1 评分。"}
            )
            warnings.append(f"{requirement.id}：已按规则忽略个人属性；混合要求请先拆分确认。")
        if requirement.ignored:
            ignored.append(requirement)
        else:
            if (requirement.operator == "min_months") != (requirement.subject is not None):
                raise ScoringError(
                    "INVALID_SCORING_INPUT", f"subject 不符合操作符：{requirement.id}"
                )
            groups.setdefault(_key(requirement), []).append(requirement)
    prepared = []
    for group in groups.values():
        group.sort(key=lambda r: r.id)
        if group[0].operator == "degree_at_least":
            policies = {_enrollment_policy(r.quote) for r in group}
            if "conflict" in policies or len(policies) > 1:
                requires_confirmation = True
                warnings.append(
                    f"{', '.join(r.id for r in group)}：在读资格条件冲突，"
                    "原始要求及原文全部保留，需用户重新确认。"
                )
                prepared.extend(group)
                continue
        representative = group[0]
        if len(group) > 1:
            merged_ids[representative.id] = tuple(r.id for r in group)
            warnings.append(
                f"重复要求 {', '.join(merged_ids[representative.id])} 合并为 {representative.id}。"
            )
            if len({r.importance for r in group}) > 1:
                representative = representative.model_copy(update={"importance": "must"})
                requires_confirmation = True
                warnings.append(f"{representative.id}：重要性冲突，草稿保留 must，需用户重新确认。")
        prepared.append(representative)
    job.requirements = sorted(prepared + ignored, key=lambda r: r.id)
    return PreparedJob(job, tuple(warnings), merged_ids, requires_confirmation)


def _references(facts: list[Fact]) -> list[str]:
    return sorted({id for fact in facts for id in fact.evidence_ids})


def _month_index(value: str) -> int:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value) or int(value[:4]) == 0:
        raise ValueError("invalid month")
    return int(value[:4]) * 12 + int(value[5:]) - 1


def _union_months(intervals: list[tuple[int, int]]) -> int:
    total = 0
    left, right = sorted(intervals)[0]
    for start, end in sorted(intervals)[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + right - left


def _degree(requirement: Requirement, profile: ProfileContent) -> tuple[Status, list[str], str]:
    target = normalized_degree(requirement.target)
    if target not in DEGREES:
        return "unknown", [], "学历阈值无法可靠计算，需确认规范学历值。"
    facts = [f for f in profile.facts if f.kind == "education"]
    positive = [f for f in facts if f.polarity == "positive" and f.value in DEGREES]
    negative = [f for f in facts if f.polarity == "negative" and f.value in DEGREES]
    # A denial of the target conflicts with direct positive support for it.
    qualifying = [f for f in positive if DEGREES[f.value] >= DEGREES[target]]
    denied = [f for f in negative if f.value == target]
    if qualifying and denied or any(p.value == n.value for p in positive for n in negative):
        return "unknown", _references(facts), "conflict：学历肯定与否定证据矛盾，需用户澄清。"
    if denied:
        return "unmet", _references(denied), "用户明确否认具备要求学历。"
    completed = [f for f in positive if f.completed is True]
    accepted = [f for f in completed if DEGREES[f.value] >= DEGREES[target]]
    if accepted:
        return "met", _references(accepted), "已完成的明确学历达到要求。"
    if qualifying:
        in_progress_accepted = _enrollment_policy(requirement.quote) == "accept"
        studying = [f for f in qualifying if f.completed is False]
        if in_progress_accepted and studying:
            return "met", _references(studying), "JD 明确接受在读，已有明确在读学历证据。"
        return "unknown", _references(qualifying), "学历尚未明确完成，JD 未明确接受该在读状态。"
    if completed:
        return "unmet", _references(completed), "最高明确已完成学历低于要求。"
    return "unknown", _references(facts), "缺少可确认的已完成学历证据。"


def _assess(requirement: Requirement, profile: ProfileContent) -> tuple[Status, list[str], str]:
    if requirement.operator == "manual_review":
        return "unknown", [], "manual_review：v1 无法可靠计算，需人工补充可核验事实。"
    if requirement.operator == "degree_at_least":
        return _degree(requirement, profile)
    label = requirement.subject if requirement.operator == "min_months" else requirement.target
    kinds = (
        {"experience", "project"}
        if requirement.operator == "min_months"
        else {"skill", "experience", "project"}
    )
    if requirement.operator == "has_evidence":
        kinds.add("education")
    facts = [
        f
        for f in profile.facts
        if f.kind in kinds and normalized_label(f.label) == normalized_label(label)
    ]
    positive = [f for f in facts if f.polarity == "positive"]
    negative = [f for f in facts if f.polarity == "negative"]
    ids = _references(facts)
    if positive and negative:
        return "unknown", ids, "conflict：同一要求存在肯定与否定证据，需用户澄清。"
    if negative:
        return "unmet", ids, "用户明确否认具备该要求，属于明确差距。"
    if not positive:
        return "unknown", [], "未提供对应证据；没有提及不等于不会。"
    if requirement.operator == "has_evidence":
        return "met", ids, "已确认事实标签完全或受控等价匹配，并有原文引用。"
    if requirement.operator == "has_skill":
        applied = [
            f
            for f in positive
            if f.kind in {"project", "experience"} and f.application == "applied"
        ]
        if applied:
            return "met", _references(applied), "项目/工作事实明确应用该技能，引用原文证据。"
        return "partial", ids, "只有技能自述，缺少项目/工作应用证据。"
    if not re.fullmatch(r"[0-9]+", requirement.target.strip()) or int(requirement.target) <= 0:
        return "unknown", ids, "最低月数必须为明确的正整数，不能补造阈值。"
    threshold = int(requirement.target)
    intervals = []
    try:
        as_of = _month_index(profile.as_of_month)
        for fact in positive:
            if fact.start_month is None:
                raise ValueError("missing start")
            end = fact.end_month
            if end is None and fact.completed is False:
                end = profile.as_of_month  # Explicitly ongoing, fixed snapshot time only.
            if end is None:
                raise ValueError("missing end")
            start_index, end_index = _month_index(fact.start_month), _month_index(end)
            if start_index > end_index or end_index > as_of:
                raise ValueError("reversed or future interval")
            intervals.append((start_index, end_index))
    except ValueError:
        return "unknown", ids, "相关经历日期缺失、倒置或超出确认时点，需澄清区间。"
    months = _union_months(intervals)
    status: Status = (
        "met" if months >= threshold else ("partial" if 2 * months >= threshold else "unmet")
    )
    return status, ids, f"相关经历 [start,end) 区间并集为 {months} 月，要求 {threshold} 月。"


def assess_requirements(
    profile_content: ProfileContent, job_content: JobContent, matcher_version: str = MATCHER_VERSION
) -> list[RequirementAssessment]:
    if matcher_version != MATCHER_VERSION:
        raise ScoringError("UNSUPPORTED_MATCHER_VERSION", f"Unsupported matcher: {matcher_version}")
    profile = ProfileContent.model_validate(profile_content.model_dump())
    evidence_ids = [e.id for e in profile.evidence]
    fact_ids = [f.id for f in profile.facts]
    if len(evidence_ids) != len(set(evidence_ids)) or len(fact_ids) != len(set(fact_ids)):
        raise ScoringError("INVALID_SCORING_INPUT", "档案事实/证据 ID 必须唯一。")
    if any(set(f.evidence_ids) - set(evidence_ids) for f in profile.facts):
        raise ScoringError("INVALID_SCORING_INPUT", "事实引用不存在的证据，不能开始评分。")
    prepared = prepare_job(job_content)
    if prepared.requires_confirmation:
        raise ScoringError("REQUIREMENTS_NEED_CONFIRMATION", "；".join(prepared.warnings))
    result = []
    for requirement in prepared.content.requirements:
        if requirement.ignored:
            continue
        status, ids, reason = _assess(requirement, profile)
        if requirement.id in prepared.merged_ids:
            reason += f" 重复要求 {', '.join(prepared.merged_ids[requirement.id])} 已合并计一次。"
        result.append(
            RequirementAssessment(
                requirement_id=requirement.id,
                category=requirement.category,
                importance=requirement.importance,
                status=status,
                weight=WEIGHTS[requirement.importance],
                coefficient=float(COEFFICIENTS[status]),
                evidence_ids=ids,
                reason=reason,
            )
        )
    return result
