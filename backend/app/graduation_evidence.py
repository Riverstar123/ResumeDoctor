"""Bounded graduation evidence with event spans and contextual qualifications."""

import calendar
import re
from datetime import date

_COMPLETION = r"(?:课程结束|完成课程|完成学业|学业完成|学业结束)"
_UNCERTAIN = re.compile(
    r"待定|待确认|未(?:能|经)?确认|尚未确定|未确定|未定|未明确|不确定|不一定|无法确定|未提供|未知|另行通知|"
    r"原计划|原定|不是|并非|不能|无法|未能|不会|延期|延后|推迟|如果|假如|假设|退学|休学|肄业|结业|^若"
)
_EN_UNCERTAIN = re.compile(
    r"\b(?:not|no|never|unknown|uncertain|unconfirmed|tbd|undecided|postponed|delayed|if|unless|withdrawn)\b",
    re.I,
)
_FOLLOWUP_PREFIXES = tuple(
    sorted(
        (
            "但是",
            "不过",
            "然而",
            "但",
            "实际",
            "目前",
            "已经",
            "仍然",
            "具体",
            "确切",
            "预计",
            "时间",
            "日期",
            "安排",
            "暂时",
            "现",
            "已",
            "仍",
            "还",
            "尚",
            "暂",
            "的",
        ),
        key=len,
        reverse=True,
    )
)
_MONTH = r"(?:0?[1-9]|1[0-2])"
_DAY = r"(?:0?[1-9]|[12][0-9]|3[01])"
_ANY_DATE = rf"[0-9]{{4}}(?:年(?:{_MONTH}月(?:{_DAY}日)?)?|[-./]{_MONTH}(?:[-./]{_DAY})?)?"


def _compact(text):
    characters, positions = [], []
    for index, character in enumerate(text):
        if character in "\r\n":
            characters.append("\n")
            positions.append(index)
        elif not character.isspace():
            for folded in character.casefold():
                characters.append(folded)
                positions.append(index)
    return "".join(characters), positions


def _followup_uncertain(clause, raw):
    # Consume controlled modifiers, not arbitrary text before '延期'. This accepts
    # '但实际已延期' but leaves '但实习日期已经推迟' attached to the internship.
    remaining = clause.strip("（）()")
    while remaining:
        token = next((p for p in _FOLLOWUP_PREFIXES if remaining.startswith(p)), None)
        if token is None:
            break
        remaining = remaining[len(token) :]
    if _UNCERTAIN.match(remaining):
        return True
    return bool(
        re.match(
            r"\s*(?:(?:but|however|actually|now|already|the|graduation|date|schedule|has|have|been|is|was|still)\s+)*"
            r"(?:delayed|postponed|unconfirmed|undecided|uncertain|tbd|not\s+(?:yet\s+)?(?:confirmed|determined))\b",
            raw,
            re.I,
        )
    )


def _date_bounds(text):
    numbers = [int(value) for value in re.findall(r"[0-9]+", text)]
    year = numbers[0]
    try:
        if len(numbers) == 1:
            return date(year, 1, 1), date(year, 12, 31)
        month = numbers[1]
        if len(numbers) == 3:
            actual = date(year, month, numbers[2])
            return actual, actual
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        return None


def _completion_before(prefix, previous, departure):
    # Completion must precede this departure in the same or adjacent clause;
    # an unrelated later occurrence of '课程结束' is not a causal relationship.
    introduction = r"(?:将于|计划于|预计于|预计|于|将)?"
    if re.fullmatch(introduction, prefix):
        completion = previous
    else:
        completion = re.sub(introduction + r"$", "", prefix)
    match = re.fullmatch(
        rf"(?P<date>{_ANY_DATE})?(?:已经|已)?{_COMPLETION}(?:之后|以后|后|了)?", completion
    )
    if match is None:
        return False
    if match["date"] is None:
        return True  # Explicit sequence, e.g. '课程结束，将于...离校'.
    finished, leaving = _date_bounds(match["date"]), _date_bounds(departure)
    return bool(finished and leaving and finished[1] <= leaving[0])


def _patterns(date_value):
    year, *months = map(int, date_value.split("-"))
    month = (rf"0?{months[0]}" if months[0] < 10 else str(months[0])) if months else _MONTH
    suffix = rf"(?:[-./]{month}(?:[-./]{_DAY})?|年{month}月(?:{_DAY}日)?)"
    suffix = suffix if months else rf"(?:{suffix}|年)?"
    value = rf"(?<!\d){year}{suffix}(?!\d)"
    boundary = r"(?=$|[()（）]|于|后|并|且)"
    patterns = [
        re.compile(
            rf"(?P<event>毕业|离校)(?:时间|日期|年份)?"
            rf"(?:(?:为|于|在|是|定于|预计|预期|计划|调整为|改为|更改为)|[:：])*(?P<date>{value}){boundary}"
        ),
        re.compile(
            rf"(?P<date>{value})[（(]?(?:预计|预期|计划)?"
            rf"(?:专科|大专|本科|学士|硕士|博士)?(?P<event>毕业|离校){boundary}"
        ),
    ]
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
    named = month_names[months[0] - 1] if months else "|".join(month_names)
    patterns.append(
        re.compile(
            rf"(?:graduation(?:date|year)?|graduat(?:e|ed|ing))"
            rf"(?:expected|in|on|is|:)*(?:{value}|(?:{named})\.?{year}(?!\d)){boundary}"
        )
    )
    if not months:
        patterns += [re.compile(rf"(?<!\d){year}届"), re.compile(rf"classof{year}(?!\d)")]
    return patterns


def _graduation_spans(quote, date_value):
    """Return raw-text event spans; None denotes explicit uncertainty/conflict."""
    compact, positions = _compact(quote)
    clauses = list(re.finditer(r"[^，,。；;！？!?\n]+", compact))
    raw_clauses = [quote[positions[c.start()] : positions[c.end() - 1] + 1] for c in clauses]
    patterns, spans = _patterns(date_value), []
    related = [bool(re.search(r"毕业|离校|届|graduat|classof", c[0])) for c in clauses]
    for index, clause in enumerate(clauses):
        text, raw = clause[0], raw_clauses[index]
        if related[index] and (
            _UNCERTAIN.search(text)
            or _EN_UNCERTAIN.search(raw)
            or re.search(rf"(?:不属于|不属|非){date_value[:4]}届", text)
        ):
            return None
        if index and related[index - 1] and _followup_uncertain(text, raw):
            return None
        for pattern in patterns:
            for match in pattern.finditer(text):
                # Parenthetical course work is not a graduation event; ordinary
                # qualifiers such as '(全日制)' do not erase an explicit event.
                if re.match(r"[（(](?:毕业)?(?:论文|设计|答辩)", text[match.end() :]):
                    continue
                if match.groupdict().get("event") == "离校":
                    if re.search(r"退学|休学|肄业", compact):
                        continue
                    if any(
                        re.search(r"课程|学业", c[0]) and _UNCERTAIN.search(c[0]) for c in clauses
                    ):
                        continue
                    prefix = text[: match.start()]
                    previous = clauses[index - 1][0] if index else ""
                    if not _completion_before(prefix, previous, match["date"]):
                        continue
                    if any(
                        other_index != index
                        and re.search(_COMPLETION, other[0])
                        and not _completion_before("", other[0], match["date"])
                        for other_index, other in enumerate(clauses)
                    ):
                        continue  # A later contradictory completion cannot be ignored.
                start, end = clause.start() + match.start(), clause.start() + match.end()
                spans.append((positions[start], positions[end - 1] + 1))
    return spans


def _conflicting_graduation_years(quotes):
    # Collect only dates attached to graduation events, not arbitrary years in
    # the same evidence (such as internship dates or course completion dates).
    years = {year for quote in quotes for year in re.findall(r"(?<!\d)\d{4}(?!\d)", quote)}
    supported = {year for year in years if any(_graduation_spans(q, year) for q in quotes)}
    return len(supported) > 1


def explicit_graduation_quote(quotes: list[str], date_value: str) -> str | None:
    if _conflicting_graduation_years(quotes):
        return None
    supported = None
    for quote in quotes:
        spans = _graduation_spans(quote, date_value)
        if spans is None:
            return None
        if spans and supported is None:
            supported = quote
    return supported


def graduation_attribute_supported(attribute_quote: str, year: str, quotes: list[str]) -> bool:
    """Accept legacy short dates only when their exact occurrences identify the event."""
    if _conflicting_graduation_years(quotes):
        return False
    if not re.search(rf"(?<!\d){year}(?!\d)", attribute_quote):
        return False
    found = False
    for quote in quotes:
        spans = _graduation_spans(quote, year)
        if spans is None:
            return False
        for occurrence in re.finditer(re.escape(attribute_quote), quote):
            found = True
            start, end = occurrence.span()
            if not any(
                left <= start and end <= right or start <= left and right <= end
                for left, right in spans
            ):
                return False  # Ambiguous repetitions cannot select a convenient occurrence.
    return found
