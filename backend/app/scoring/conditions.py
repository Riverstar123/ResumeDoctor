"""matcher-v2: bounded condition algebra over confirmed evidence, without model I/O."""

import re
from dataclasses import dataclass

from app.contracts import Fact, JobContent, ProfileContent, Requirement, RequirementAssessment
from app.contracts.models import Criterion
from app.structured_fields import (
    ATTRIBUTE_KINDS,
    NUMERIC_FIELDS,
    education_status_conflict,
    validate_condition,
)

from .calculator import COEFFICIENTS, WEIGHTS
from .errors import ScoringError
from .vocabulary import normalized_label

# Equivalences and parent membership are deliberately different. A component can
# support partial suite coverage; it never proves mastery of the entire suite.
EQUIVALENTS = {
    "microsoft office": "office",
    "ms office": "office",
    "微软office": "office",
    "microsoft excel": "excel",
    "ms excel": "excel",
    "microsoft powerpoint": "powerpoint",
    "ppt": "powerpoint",
    "microsoft word": "word",
    "adobe photoshop": "photoshop",
    "金融学": "金融",
    "finance": "金融",
    "经济学": "经济",
    "economics": "经济",
    "computer science": "计算机科学",
}
SUITES = {
    "office": {"excel", "powerpoint", "word", "outlook", "access", "onenote"},
    "adobe creative cloud": {
        "photoshop",
        "illustrator",
        "indesign",
        "premiere pro",
        "after effects",
    },
}
FIELD_LABELS = {
    "institution": "院校",
    "major": "专业",
    "graduation_year": "毕业年份",
    "enrollment": "在读状态",
    "experience_type": "经历类型",
    "experience_domain": "经历领域",
    "availability_days": "每周可到岗天数",
    "availability_months": "未来可连续任职月数",
    "availability_start": "到岗时间",
    "full_time": "全职安排",
}


def candidate_kinds(field: str) -> set[str]:
    if field == "skill":
        return {"skill", "experience", "project"}
    if field == "credential":
        return {"credential"}
    if field == "manual":
        return set()  # Manual conditions cannot select a single fact.
    return ATTRIBUTE_KINDS.get(field, set())


def education_date_conflict(fact: Fact) -> bool:
    years = {a.value for a in fact.attributes if a.name == "graduation_year"}
    return bool(years and fact.end_month and years != {fact.end_month[:4]})


def credential_names(fact: Fact) -> set[str]:
    """A separately confirmed level may qualify the name, without fuzzy matching."""
    original = label(fact.label)
    names = {original}
    for attribute in fact.attributes:
        if attribute.name != "credential_level":
            continue
        level = label(attribute.value)
        for suffix in (" " + level, "(" + level + ")", "（" + level + "）"):
            if original.endswith(suffix) and original[: -len(suffix)].strip():
                names.add(original[: -len(suffix)].strip())
    return names


def label(value: str) -> str:
    value = normalized_label(value)
    return EQUIVALENTS.get(value, value)


@dataclass(frozen=True)
class Outcome:
    status: str
    ids: tuple[str, ...]
    reason: str
    unknown_reason: str | None = None


def refs(facts: list[Fact]) -> tuple[str, ...]:
    return tuple(sorted({eid for fact in facts for eid in fact.evidence_ids}))


def combine(results: list[Outcome], *, any_of: bool) -> Outcome:
    """Three-valued logic with partial evidence; an OR is counted once."""
    statuses = {result.status for result in results}
    if any_of:
        if "met" in statuses:
            selected = [result for result in results if result.status == "met"]
            status = "met"
        elif "partial" in statuses:
            selected = [result for result in results if result.status == "partial"]
            status = "partial"
        else:
            selected = results
            status = "unknown" if "unknown" in statuses else "unmet"
    else:
        selected = results
        status = (
            "unmet"
            if "unmet" in statuses
            else "unknown"
            if "unknown" in statuses
            else "partial"
            if "partial" in statuses
            else "met"
        )
    cause = None
    if status == "unknown":
        causes = {r.unknown_reason for r in selected if r.status == "unknown"}
        cause = next(
            (
                c
                for c in (
                    "conflicting_evidence",
                    "missing_evidence",
                    "unsupported_condition",
                    "manual_review",
                )
                if c in causes
            ),
            "unsupported_condition",
        )
    return Outcome(
        status,
        tuple(sorted({eid for r in selected for eid in r.ids})),
        "；".join(dict.fromkeys(r.reason for r in selected)),
        cause,
    )


def assess_atom(
    criterion: Criterion,
    facts: list[Fact],
    profile: ProfileContent,
    *,
    current_presence: bool = False,
) -> Outcome:
    field, target = criterion.field, label(criterion.value)
    field_name = FIELD_LABELS.get(field, field)
    if field == "manual":
        return Outcome(
            "unknown",
            refs(facts),
            "此条件需人工判断；已有材料保留供核对，不等于未提供。",
            "manual_review",
        )
    if field == "skill":
        candidates = [
            f
            for f in facts
            if f.kind in {"skill", "experience", "project"} and label(f.label) == target
        ]
        components = [
            f
            for f in facts
            if f.kind in {"skill", "experience", "project"}
            and label(f.label) in SUITES.get(target, set())
            and f.polarity == "positive"
        ]
        positive = [f for f in candidates if f.polarity == "positive"]
        negative = [f for f in candidates if f.polarity == "negative"]
        if positive and negative:
            return Outcome(
                "unknown",
                refs(candidates),
                "conflict：技能肯定与否定证据冲突。",
                "conflicting_evidence",
            )
        if negative:
            return Outcome("unmet", refs(negative), "有明确否定证据。")
        applied = [
            f
            for f in positive
            if f.kind in {"experience", "project"} and f.application == "applied"
        ]
        if applied:
            return Outcome("met", refs(applied), f"{criterion.value} 有项目或工作应用证据。")
        if positive or components:
            return Outcome(
                "partial",
                refs(positive or components),
                "仅有技能自述，尚缺应用证据。"
                if positive
                else "已有套件组成工具的证据；仅支持部分覆盖，不代表熟练整个套件。",
            )
        return Outcome("unknown", (), f"未提供 {criterion.value} 的对应证据。", "missing_evidence")
    if field == "credential":
        candidates = [f for f in facts if f.kind == "credential" and target in credential_names(f)]
        positive = [f for f in candidates if f.polarity == "positive"]
        negative = [f for f in candidates if f.polarity == "negative"]
        if positive and negative:
            return Outcome(
                "unknown", refs(candidates), "conflict：证书陈述互相矛盾。", "conflicting_evidence"
            )
        if negative:
            return Outcome("unmet", refs(negative), "明确否认具备该证书或考试进度。")
        states = {
            "partial" if a.value == "complete" and label(f.label) != target else a.value
            for f in positive
            for a in f.attributes
            if a.name == "credential_status"
        }
        if len(states) > 1:
            return Outcome(
                "unknown",
                refs(positive),
                "conflict：证书进度记录冲突，需确认当前状态。",
                "conflicting_evidence",
            )
        if not states:
            return Outcome(
                "unknown", refs(positive), "缺少可确认的证书考试进度。", "missing_evidence"
            )
        state = next(iter(states))
        met = state == "complete" or (state == "partial" and criterion.comparison == "any_pass")
        return Outcome(
            "met" if met else "unmet",
            refs(positive),
            "已有满足要求的证书/部分考试通过记录。"
            if met
            else "已有考试状态不满足本项条件；备考不等于通过，部分通过不等于完整资格。",
        )
    candidates = [f for f in facts if f.kind in ATTRIBUTE_KINDS.get(field, set())]
    if field == "enrollment":
        conflicts = [f for f in candidates if education_status_conflict(f)]
        if conflicts:
            return Outcome(
                "unknown",
                refs(conflicts),
                "学历完成状态与在读属性矛盾，需澄清。",
                "conflicting_evidence",
            )
    if field in {"graduation_year", "enrollment"}:
        conflicts = [
            f for f in candidates if f.polarity == "positive" and education_date_conflict(f)
        ]
        if conflicts:
            if field == "graduation_year" and criterion.comparison in {"gte", "lte", "eq"}:
                values = {int(a.value) for f in conflicts for a in f.attributes if a.name == field}
                values.update(int(f.end_month[:4]) for f in conflicts)
                threshold = int(criterion.value)
                decisions = {
                    v >= threshold
                    if criterion.comparison == "gte"
                    else v <= threshold
                    if criterion.comparison == "lte"
                    else v == threshold
                    for v in values
                }
                if decisions == {True} and not any(f.polarity == "negative" for f in candidates):
                    return Outcome(
                        "met",
                        refs(conflicts),
                        "届别与教育结束年份不一致，但两个记载均满足本项年份门槛；具体毕业时间仍需核对。",
                    )
            return Outcome(
                "unknown",
                refs(conflicts),
                "学历届别与教育结束日期冲突，需确认当前在读状态及毕业年份。",
                "conflicting_evidence",
            )
    entries = [(f, a) for f in candidates for a in f.attributes if a.name == field]
    positive = [(f, a) for f, a in entries if f.polarity == "positive"]
    negative = [(f, a) for f, a in entries if f.polarity == "negative"]

    def canonical(value: str) -> str:
        if field == "availability_start" and value == "immediate":
            return profile.as_of_month
        return label(value)

    def matches(value: str) -> bool | None:
        if criterion.comparison == "exists":
            if (
                current_presence
                and field == "availability_start"
                and value != "immediate"
                and value < profile.as_of_month
            ):
                return None
            return True
        if field == "availability_start" and criterion.value == "immediate":
            if value == "immediate":
                return True
            # A month alone cannot promise availability at this exact moment.
            return False if value > profile.as_of_month else None
        if criterion.comparison == "eq":
            return canonical(value) == target
        if field in NUMERIC_FIELDS:
            left, right = int(value), int(criterion.value)
        elif field == "availability_start":
            left, right = canonical(value), criterion.value
        else:
            return False
        return left >= right if criterion.comparison == "gte" else left <= right

    qualifying = [(f, a) for f, a in positive if matches(a.value)]
    denied = [(f, a) for f, a in negative if matches(a.value)]
    # Conflicting values on one fact cannot be silently resolved. Different
    # education/work facts may legitimately have different values.
    single_valued = field not in {"major", "experience_domain"}
    conflicting = single_valued and any(
        len({label(a.value) for ff, a in positive if ff.id == f.id}) > 1 for f in candidates
    )
    conflict_facts = candidates
    # same_fact limits which facts may satisfy a conjunction, not which current
    # commitments can contradict it. Check availability against the full snapshot.
    if field.startswith("availability_") or field == "full_time":
        conflict_facts = [
            f
            for f in profile.facts
            if f.kind == "availability" and any(a.name == field for a in f.attributes)
        ]
        all_entries = [(f, a) for f in conflict_facts for a in f.attributes if a.name == field]
        all_positive = [(f, a) for f, a in all_entries if f.polarity == "positive"]
        all_negative = [(f, a) for f, a in all_entries if f.polarity == "negative"]
        positive_values = {canonical(a.value) for _, a in all_positive}
        negative_values = {canonical(a.value) for _, a in all_negative}
        conflicting = (
            len(positive_values) > 1
            or bool(positive_values & negative_values)
            or (
                any(matches(a.value) is True for _, a in all_positive)
                and any(matches(a.value) is True for _, a in all_negative)
            )
        )
    if conflicting or qualifying and denied:
        return Outcome(
            "unknown",
            refs(conflict_facts),
            f"conflict：{field_name}证据矛盾，需确认。",
            "conflicting_evidence",
        )
    if not entries:
        return Outcome(
            "unknown",
            refs(candidates),
            f"已有相关材料，但缺少明确的{field_name}字段。"
            if candidates
            else f"未提供{field_name}的明确证据。",
            "missing_evidence",
        )
    if denied:
        return Outcome("unmet", refs([f for f, _ in denied]), f"明确否认满足{field_name}条件。")
    if qualifying:
        return Outcome("met", refs([f for f, _ in qualifying]), f"{field_name}的明确记录满足条件。")
    uncertain = [f for f, a in positive if matches(a.value) is None]
    if uncertain:
        return Outcome(
            "unknown",
            refs(uncertain),
            "已有到岗记录早于资料截止月份，需重新确认当前安排。"
            if criterion.comparison == "exists"
            else "已有月份不足以确认立即到岗承诺，请核对当前安排。",
            "missing_evidence",
        )
    if positive:
        # A different specialization is not proof that no related specialization
        # exists; a numerical ceiling/explicit availability, however, is decisive.
        status = (
            "unmet"
            if field in NUMERIC_FIELDS or field in {"enrollment", "full_time", "availability_start"}
            else "unknown"
        )
        return Outcome(
            status,
            refs([f for f, _ in positive]),
            f"现有{field_name}记录未满足该条件；不推断未记录信息。",
            "missing_evidence" if status == "unknown" else None,
        )
    return Outcome("unknown", refs(candidates), f"无法确认{field_name}条件。", "missing_evidence")


# Presence requests carry no threshold. Keep the vocabulary finite: dates in
# arbitrary targets or requirements with timing thresholds do not match here.
_PRESENCE_FIELDS = {
    "毕业时间": "graduation_year",
    "提供毕业时间": "graduation_year",
    "明确提供毕业时间": "graduation_year",
    "到岗日期": "availability_start",
    "可到岗日期": "availability_start",
    "提供可到岗日期": "availability_start",
    "到岗时间": "availability_start",
    "提供到岗时间": "availability_start",
}

# These are exact names for the same presence request, not fuzzy date matching.
_PRESENCE_FIELDS.update(
    {
        prefix + name: "graduation_year"
        for prefix in ("", "提供", "明确提供")
        for name in ("毕业时间", "毕业日期", "预计毕业时间", "预计毕业日期")
    }
)


def explicit_graduation_quote(quotes: list[str], end_month: str) -> str | None:
    """A course end date and a separate graduation word do not establish linkage."""
    year, month = map(int, end_month.split("-"))
    date = rf"(?<!\d){year}(?:[-./]0?{month}(?:[-./](?:0?[1-9]|[12]\d|3[01]))?|年0?{month}月(?:0?[1-9]日|[12]\d日|3[01]日)?)(?!\d)"
    before = re.compile(
        rf"毕业(?:时间|日期)?(?:(?:为|于|在|是|定于|预计|预期|计划)|[:：])*{date}(?:[（(](?:预计|预期)[)）])?(?=$|[)）])"
    )
    after = re.compile(rf"{date}[（(]?(?:预计|预期|计划)?毕业(?=$|[)）]|于|后|并|且)")
    candidates = []
    for quote in quotes:
        for raw_clause in re.split(r"[，,。；;！？!?\n]", quote):
            clause = "".join(raw_clause.split())
            if "毕业" in clause and re.search(
                r"待定|待确认|尚未确定|未确定|未定|未明确|不确定|不一定|无法确定|未提供|未知|另行通知|原计划|原定|不是|并非|不能|无法|未能|不会|延期|延后|如果|假如|假设|若",
                clause,
            ):
                return None
            if before.search(clause) or after.search(clause):
                candidates.append(quote)
    return candidates[0] if candidates else None


def assess_presence(requirement: Requirement, profile: ProfileContent) -> Outcome | None:
    field = _PRESENCE_FIELDS.get(label(requirement.target))
    if field is None:
        return None
    # The whole clause must ask only for a record. A model may have omitted a
    # deadline from target; do not turn that narrower target into proof of it.
    clause = "".join(requirement.quote.split())
    if not re.fullmatch(
        r"(?:请|需|需要|须|必须|要求)?(?:明确)?(?:提供|注明|写明)?"
        r"(?:预计毕业时间|预计毕业日期|毕业时间|毕业日期|可到岗日期|到岗日期|到岗时间)[。；;.]?",
        clause,
    ):
        return Outcome(
            "unknown",
            refs([f for f in profile.facts if f.kind in candidate_kinds(field)]),
            "日期证明还包含无法由记录存在直接判断的限制，需人工核对。",
            "unsupported_condition",
        )
    facts = profile.facts
    if field == "graduation_year":
        from app.contracts.models import FactAttribute

        evidence = {item.id: item.quote for item in profile.evidence}
        facts = []
        for fact in profile.facts:
            projected = fact
            if (
                fact.kind == "education"
                and fact.end_month
                and not any(a.name == field for a in fact.attributes)
            ):
                year = fact.end_month[:4]
                quotes = [evidence[eid] for eid in fact.evidence_ids]
                quote = explicit_graduation_quote(quotes, fact.end_month)
                if quote is not None:
                    projected = fact.model_copy(
                        update={
                            "attributes": [
                                *fact.attributes,
                                FactAttribute(name=field, value=str(year), quote=quote),
                            ]
                        }
                    )
            facts.append(projected)
    return assess_atom(
        Criterion(field=field, comparison="exists", value=field, quote=requirement.quote),
        facts,
        profile,
        current_presence=True,
    )


def assess_v2(
    profile: ProfileContent, job: JobContent, *, recognize_presence: bool = False
) -> list[RequirementAssessment]:
    from .matcher import _assess, prepare_job

    if recognize_presence:
        # Versioned equivalences: old v2 snapshots must still reproduce their
        # original assessment. Normalize copies for matching, never the source.
        def language_name(value: str) -> str:
            return "英文财报阅读" if normalized_label(value) == "英语财报阅读" else value

        profile = profile.model_copy(
            update={
                "facts": [
                    f.model_copy(update={"label": language_name(f.label)}) for f in profile.facts
                ]
            }
        )
        job = job.model_copy(deep=True)
        for requirement in job.requirements:
            if requirement.operator == "has_skill":
                requirement.target = language_name(requirement.target)
            if requirement.condition:
                for group in requirement.condition.any_of:
                    for criterion in group.all_of:
                        if criterion.field == "skill":
                            criterion.value = language_name(criterion.value)

    def check_atom(criterion, selected):
        return assess_atom(criterion, selected, profile, current_presence=recognize_presence)

    prepared = prepare_job(job)
    if prepared.requires_confirmation:
        raise ScoringError("REQUIREMENTS_NEED_CONFIRMATION", "；".join(prepared.warnings))
    result = []
    for requirement in prepared.content.requirements:
        if requirement.ignored:
            continue
        try:
            validate_condition(requirement)
        except ValueError as error:
            raise ScoringError("INVALID_SCORING_INPUT", str(error)) from None
        if requirement.condition is not None:
            branches = []
            for group in requirement.condition.any_of:
                if group.scope == "same_fact":
                    kinds = set.intersection(*(candidate_kinds(c.field) for c in group.all_of))
                    candidates = [f for f in profile.facts if f.kind in kinds]
                    # A single fact must satisfy the conjunction, but cannot
                    # override contradictory evidence about the same named skill
                    # or credential elsewhere in the frozen profile. Keep other
                    # education/experience records independent.
                    conflicts = {}
                    for index, criterion in enumerate(group.all_of):
                        if criterion.field in {"skill", "credential"}:
                            checked = check_atom(criterion, profile.facts)
                            if checked.unknown_reason == "conflicting_evidence":
                                conflicts[index] = checked
                    trials = [
                        combine(
                            [
                                conflicts[index] if index in conflicts else check_atom(c, [f])
                                for index, c in enumerate(group.all_of)
                            ],
                            any_of=False,
                        )
                        for f in candidates
                    ]
                    branches.append(
                        combine(trials, any_of=True)
                        if trials
                        else Outcome("unknown", (), "没有可核对事实。", "missing_evidence")
                    )
                else:
                    branches.append(
                        combine(
                            [check_atom(c, profile.facts) for c in group.all_of],
                            any_of=False,
                        )
                    )
            outcome = combine(branches, any_of=True)
        elif requirement.operator == "manual_review":
            kind = {"education": "education", "experience": "experience", "project": "project"}.get(
                requirement.category
            )
            facts = [
                f
                for f in profile.facts
                if f.kind == kind or label(f.label) == label(requirement.target)
            ]
            outcome = Outcome(
                "unknown",
                refs(facts),
                "此条件需人工判断，现有相关证据已附；不等于简历没有写，也不自动要求补写。",
                "manual_review",
            )
        elif requirement.operator == "has_skill":
            outcome = check_atom(
                Criterion(
                    field="skill",
                    comparison="eq",
                    value=requirement.target,
                    quote=requirement.quote,
                ),
                profile.facts,
            )
        elif (
            recognize_presence
            and requirement.operator == "has_evidence"
            and (presence := assess_presence(requirement, profile)) is not None
        ):
            outcome = presence
        else:
            conflicts = (
                [f for f in profile.facts if education_status_conflict(f)]
                if requirement.operator == "degree_at_least"
                else []
            )
            usable = (
                profile.model_copy(
                    update={"facts": [f for f in profile.facts if f not in conflicts]}
                )
                if conflicts
                else profile
            )
            status, ids, reason = _assess(requirement, usable)
            if conflicts and status != "met":
                status = "unknown"
                ids = sorted(set(ids) | set(refs(conflicts)))
                reason = "conflict：学历完成状态与在读属性矛盾，不能确认已完成学历。"
            cause = (
                ("conflicting_evidence" if "conflict" in reason else "missing_evidence")
                if status == "unknown"
                else None
            )
            outcome = Outcome(status, tuple(ids), reason, cause)
        result.append(
            RequirementAssessment(
                requirement_id=requirement.id,
                category=requirement.category,
                importance=requirement.importance,
                status=outcome.status,
                weight=WEIGHTS[requirement.importance],
                coefficient=float(COEFFICIENTS[outcome.status]),
                evidence_ids=list(outcome.ids),
                reason=outcome.reason,
                unknown_reason=outcome.unknown_reason,
                counted_in_score=outcome.unknown_reason
                not in {"manual_review", "unsupported_condition"},
            )
        )
    return result
