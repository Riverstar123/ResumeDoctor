"""M3 语义校验：把档案与 JD 内容验到「可以保存、可以评分」的程度。

这里只做纯校验与规范化：不访问数据库、不调用模型、不产生任何副作用。
「证据引用必须是来源原文的真实子串」这条规则需要原文，因此由调用方（M2）
把来源文本传进来，本模块不自己去读文件或消息。
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.business_calendar import business_today
from app.contracts import Evidence, Fact, JobContent, ProfileContent, Requirement
from app.profile_dates import invalid_future_end
from app.structured_fields import condition_key, validate_attributes, validate_condition

from .errors import IntakeError

# 学历取值受控（03-database.md 数据字典）；degree_at_least 只能比较可排序的四档。
EDUCATION_VALUES = frozenset({"associate", "bachelor", "master", "doctorate", "other"})
DEGREE_TARGETS = frozenset({"associate", "bachelor", "master", "doctorate"})

# 只用 ASCII 数字，避免 int() 接受全角数字或其它 Unicode 数字。
_POSITIVE_INTEGER = re.compile(r"[0-9]+")

# Only normalize explicit tool + task clauses. Shared quotes alone do not prove
# equivalence: one sentence may contain several independent requirements.
_TASK_VERB = r"(?:清洗|分析|处理|整理|查询|统计|制作|绘制|搭建|构建|开发|编写|撰写|建立|生成|计算)"
_TASK_OBJECT_CHAR = r"[\u4e00-\u9fffA-Za-z0-9 ]"
_TOOL_TASK = re.compile(
    r"(?:(?:必须|要求|需要|能够|能|熟练|会)\s*)*"
    # Actions start with Chinese characters, so the Latin tool span has a
    # unique end. Do not redistribute its spaces into the following separator.
    r"(?:使用|利用|运用|用)\s*(?P<tool>[A-Za-z][A-Za-z0-9+#. -]*+)\s*"
    r"(?:进行|完成)?"
    # Keep a nonempty object, but never retry every action/object split when a
    # long clause has an invalid suffix. Object characters exclude punctuation.
    rf"(?P<actions>{_TASK_VERB}(?:(?:和|与|及){_TASK_VERB}(?={_TASK_OBJECT_CHAR}))*+)"
    rf"(?P<object>{_TASK_OBJECT_CHAR}++)[。.!！]?"
)
_SEPARATE_CONDITION = re.compile(r"并|且|同时|另外|需要|要求|熟悉|掌握|至少|以上|或者|或|不|未")


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
    previously_verified_evidence: Sequence[Evidence] = (),
) -> ProfileValidation:
    """校验档案内容，返回可保存的结果。

    sources 是「来源 ID → 该来源的原文」，用于核对 evidence.quote。
    today 仅用于测试注入，默认取北京时间日期判断 as_of_month 是否来自未来。
    previously_verified_evidence 只能来自调用方已校验并保存的上一快照。
    完全未变的证据不要求重新加载已清理的文件或窗口外的历史原文；新增或修改的
    证据仍必须通过 sources 校验，不能将模型本轮输出传入这个参数。
    """
    reference_day = today or business_today()
    _require_as_of_month_not_future(content.as_of_month, reference_day)
    _require_unique_ids([fact.id for fact in content.facts], "事实")
    _require_unique_ids([item.id for item in content.evidence], "证据")

    verified = {item.id: item for item in previously_verified_evidence}
    known_evidence_ids = {item.id for item in content.evidence}
    for item in content.evidence:
        if item != verified.get(item.id):
            _require_quote_from_source(item, sources)

    for fact in content.facts:
        missing = [eid for eid in fact.evidence_ids if eid not in known_evidence_ids]
        if missing:
            raise IntakeError(
                "UNKNOWN_EVIDENCE_REFERENCE",
                f"事实 {fact.id} 引用了档案中不存在的证据：{', '.join(missing)}",
            )
        _require_month_range(fact)
        if invalid_future_end(fact, content.as_of_month):
            raise IntakeError("FUTURE_END_DATE", "非在读教育的结束月份晚于档案截止月份")
        _require_education_value(fact)
        try:
            validate_attributes(
                fact,
                [e.quote for e in content.evidence if e.id in fact.evidence_ids],
                evidence=[e for e in content.evidence if e.id in fact.evidence_ids],
            )
        except ValueError as error:
            raise IntakeError("INVALID_FACT_ATTRIBUTE", str(error)) from None

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

    atomic = []
    used_ids = {r.id for r in content.requirements}
    for requirement in content.requirements:
        condition = requirement.condition
        # A plain list of named tools is not a disjunction. Only explicit
        # alternatives can reduce it to one weighted requirement.
        plain_skill_list = (
            condition
            and len(condition.any_of) > 1
            and all(
                g.scope == "profile" and len(g.all_of) == 1 and g.all_of[0].field == "skill"
                for g in condition.any_of
            )
            and not re.search(
                r"或|任一|之一|任选|任意|至少.{0,4}一种|/|\bor\b|\beither\b",
                requirement.quote,
                re.I,
            )
        )
        if plain_skill_list:
            condition = condition.model_copy(
                update={
                    "any_of": [
                        condition.any_of[0].model_copy(
                            update={"all_of": [g.all_of[0] for g in condition.any_of]}
                        )
                    ]
                }
            )
        if (
            condition
            and len(condition.any_of) == 1
            and condition.any_of[0].scope == "profile"
            and len(condition.any_of[0].all_of) > 1
            and all(c.field == "skill" for c in condition.any_of[0].all_of)
        ):
            for index, criterion in enumerate(condition.any_of[0].all_of, 1):
                rid = f"{requirement.id}-skill-{index}"
                while rid in used_ids:
                    rid += "-1"
                used_ids.add(rid)
                atomic.append(
                    requirement.model_copy(
                        update={
                            "id": rid,
                            "operator": "has_skill",
                            "target": criterion.value,
                            "quote": criterion.quote,
                            "condition": None,
                        }
                    )
                )
        else:
            atomic.append(requirement)
    normalized = _normalize_tool_tasks(atomic)
    merged, warnings = _merge_duplicate_requirements(normalized)
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
    try:
        validate_condition(requirement)
    except ValueError as error:
        raise IntakeError("INVALID_REQUIREMENT_CONDITION", str(error)) from None
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


def _task_name(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold()
    return re.sub(rf"({_TASK_VERB})(?:和|与|及)(?={_TASK_VERB})", r"\1、", compact)


def _normalize_tool_tasks(requirements: Sequence[Requirement]) -> list[Requirement]:
    """Map a repeated task description to its explicit tool requirement.

    Both candidates must cite the same entire clause and use has_skill/skill.
    Keep importance, IDs and ignore state so the existing merge/conflict rules
    handle those fields. Never mutate a model output or saved snapshot in place.
    """
    # Group only for this validation call: successful AND failed parses are
    # shared, without caching users' JD text across requests.
    by_quote: dict[str, list[Requirement]] = {}
    for item in requirements:
        if item.operator == "has_skill" and item.category == "skill":
            by_quote.setdefault(item.quote.strip(), []).append(item)
    tools_by_quote = {}
    for quote, items in by_quote.items():
        match = _TOOL_TASK.fullmatch(quote)
        if not match or _SEPARATE_CONDITION.search(match["object"]):
            continue
        tool_name = _task_name(match["tool"])
        tasks = {
            _task_name(match["actions"] + match["object"]),
            _task_name(match["object"] + match["actions"]),
        }
        for item in items:
            if _task_name(item.target) == tool_name:
                tools_by_quote[quote] = (item.target, tasks)

    result = []
    for item in requirements:
        tool = tools_by_quote.get(item.quote.strip())
        if (
            tool is not None
            and item.operator == "has_skill"
            and item.category == "skill"
            and _task_name(item.target) in tool[1]
        ):
            item = item.model_copy(update={"target": tool[0]})
        result.append(item)
    return result


def _requirement_key(requirement: Requirement) -> tuple[str, str, str, str, str]:
    """重复识别键：operator/target/subject/category 加原文，规范化后比较。

    原文一并入键，这样「接受在读」和「不接受在读」这类结构相同、限制不同的要求
    不会被当成同一条静默合并。
    """
    return (
        requirement.operator,
        condition_key(requirement)
        if requirement.condition
        else requirement.target.strip().casefold(),
        (requirement.subject or "").strip().casefold(),
        requirement.category,
        requirement.quote.strip(),
    )


def _merge_duplicate_requirements(
    requirements: Sequence[Requirement],
) -> tuple[list[Requirement], tuple[str, ...]]:
    """合并完全重复的要求，保留首次出现的顺序。

    只有 operator/target/subject/category 与原文都相同时才自动合并；其余差异按性质分开处理：

    - 结构相同但原文不同：抛 REQUIREMENT_CONFLICT。静默丢弃会让分数随顺序变化，
      静默保留又会重复加权，两者都不能自动决定。
    - 原文相同但 ignored 相反：抛 REQUIREMENT_CONFLICT。ignored 决定是否进分母，
      保留哪一条都会让分数随输入顺序变化。
    - 仅 target/subject 写法或排除原因不同：保留第一条并返回 warning，不阻断保存。
    - 仅重要性不同：保留 must 并返回 warning。
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

        if existing.ignored != requirement.ignored:
            raise IntakeError(
                "REQUIREMENT_CONFLICT",
                f"要求 {existing.id} 与 {requirement.id} 内容相同但忽略状态相反"
                f"（{existing.ignored} / {requirement.ignored}），"
                "会改变计分分母，请用户确认后再提交。",
            )

        notes: list[str] = []
        if (existing.target, existing.subject, existing.quote) != (
            requirement.target,
            requirement.subject,
            requirement.quote,
        ):
            notes.append(f"两条写法不同（{existing.target!r} / {requirement.target!r}）")
        if existing.ignored and (existing.ignore_reason or "") != (requirement.ignore_reason or ""):
            notes.append("两条的排除原因不同")
        if existing.importance != requirement.importance:
            notes.append("重要性冲突，已按 must 计算")

        if existing.importance == "preferred" and requirement.importance == "must":
            merged[index] = requirement

        if notes:
            warnings.append(
                f"要求 {existing.id} 与 {requirement.id} 重复，" + "；".join(notes) + "。"
            )
        else:
            warnings.append(f"要求 {requirement.id} 与 {existing.id} 重复，已合并为一条。")

    return merged, tuple(warnings)
