"""Safe output rejection categories and locations; never log provider/user text."""

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

_FIELDS = frozenset(
    {
        "summary",
        "gaps",
        "suggestions",
        "actions",
        "requirement_id",
        "kind",
        "description",
        "evidence_ids",
        "original",
        "revised",
        "rationale",
        "requires_user_input",
        "priority",
        "horizon",
        "task",
        "done_when",
        "checks",
        "item_id",
        "verdict",
        "supports",
        "issues",
        "field",
        "quote",
        "reason",
        "evidence_checks",
        "evidence_id",
        "score_result",
        "assessments",
        "score",
        "model_metadata",
        "choices",
        "message",
        "tool_calls",
        "arguments",
        "finish_reason",
        "content",
        "function",
        "name",
        "type",
    }
)
_trace: ContextVar[str | None] = ContextVar("report_trace_id", default=None)
_capture: ContextVar[Any] = ContextVar("report_capture", default=None)
_metadata: ContextVar[dict] = ContextVar("report_metadata", default={})
_logger = logging.getLogger(__name__)


def field_path(parts: Sequence[Any]) -> str:
    """Unknown object keys can contain PII/instructions; never copy them to logs."""
    return "/" + "/".join(
        str(p) if type(p) is int and p >= 0 or isinstance(p, str) and p in _FIELDS else "*"
        for p in parts
    )


@dataclass(frozen=True)
class OutputIssue:
    path: str
    check: str
    start: int | None = None
    end: int | None = None
    sentence: int | None = None
    value_digest: str | None = None
    verdict: str | None = None
    occurrences: int | None = None


def locate(parts, check: str, text: str | None = None, quote: str | None = None, *, verdict=None):
    occurrences = text.count(quote) if isinstance(text, str) and quote else None
    start = text.find(quote) if isinstance(text, str) and quote else -1
    if start < 0:
        start = 0 if isinstance(text, str) else None
        end = len(text) if isinstance(text, str) else None
    else:
        end = start + len(quote)
    if occurrences is not None and occurrences > 1:
        # Repeated text cannot identify which occurrence the reviewer meant.
        start = end = None
    sentence = (
        len(re.findall(r"[。！？!?；;\n]+", text[:start]))
        if isinstance(text, str) and start is not None
        else None
    )
    return OutputIssue(
        field_path(parts),
        check,
        start,
        end,
        sentence,
        hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None,
        verdict,
        occurrences,
    )


def output_issues(error: Exception) -> tuple[OutputIssue, ...]:
    return tuple(i for i in getattr(error, "issues", ()) if isinstance(i, OutputIssue))[:12]


def diagnostic_event(error: Exception, *, phase: str, attempt: int = 0, candidate=None) -> dict:
    reason = getattr(error, "reason_code", None)
    event = {
        "trace_id": _trace.get(),
        "phase": phase,
        "attempt": attempt,
        "reason_code": reason
        if isinstance(reason, str) and reason in OUTPUT_REASONS
        else "UNCLASSIFIED",
        "issues": [asdict(i) for i in output_issues(error)],
    }
    event.update(_metadata.get())
    if isinstance(candidate, Mapping):
        event["candidate_digest"] = hashlib.sha256(
            json.dumps(dict(candidate), ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
    return event


def log_rejection(error: Exception, *, phase: str, attempt: int = 0, candidate=None) -> None:
    event = diagnostic_event(error, phase=phase, attempt=attempt, candidate=candidate)
    _logger.warning("report_output_rejected %s", json.dumps(event, ensure_ascii=False))


@contextmanager
def report_trace(
    observer=None,
    *,
    profile_id=None,
    job_id=None,
    profile_version=None,
    job_version=None,
    prompt_version=None,
    gateway_version=None,
):
    """An observer is an explicit local replay hook, never enabled by production."""
    trace_id = str(uuid4())
    token = _trace.set(trace_id)
    capture_token = _capture.set(observer)
    metadata = {
        "profile_id": profile_id,
        "job_id": job_id,
        "profile_version": profile_version,
        "job_version": job_version,
    }
    for name, value in (("prompt_version", prompt_version), ("gateway_version", gateway_version)):
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", value):
            metadata[name] = value
    metadata_token = _metadata.set(metadata)
    try:
        yield trace_id
    finally:
        _capture.reset(capture_token)
        _metadata.reset(metadata_token)
        _trace.reset(token)


def capture_output(phase: str, data: Any) -> None:
    observer = _capture.get()
    if observer is not None:
        try:
            from copy import deepcopy

            observer({"trace_id": _trace.get(), "phase": phase, "data": deepcopy(data)})
        except Exception:
            _logger.warning("report_capture_unavailable trace_id=%s", _trace.get())


def pydantic_issues(error) -> tuple[OutputIssue, ...]:
    return tuple(
        locate(e.get("loc", ()), "SCHEMA_INVALID")
        for e in error.errors(include_input=False, include_url=False)[:12]
    )


OUTPUT_REASONS = frozenset(
    {
        "JSON_INVALID",
        "SCHEMA_INVALID",
        "OUTPUT_TRUNCATED",
        "UNSUPPORTED_NUMBERS",
        "REFERENCE_INVALID",
        "REPORT_VALIDATION_FAILED",
        "REPORT_GROUNDING_REJECTED",
        "REPORT_REVIEW_INCOMPLETE",
        "REPORT_REVIEW_INVALID",
        "PROFILE_DATE_INVALID",
        "FUTURE_END_DATE",
        "STRUCTURED_ATTRIBUTE_INVALID",
        "UNSUPPORTED_TEMPLATE",
    }
)

REPAIR_HINTS = {
    "UNSUPPORTED_TEMPLATE": (
        "coverage-v2/v3 不输出依赖未知事实的简历模板。删除 requires_user_input=true 的建议，"
        "把待确认信息移入 actions；不能直接把标志改为 false 绕过校验。"
        "只保留能被已有证据完整支持的改写，没有则 suggestions=[]。"
    ),
    "STRUCTURED_ATTRIBUTE_INVALID": (
        "核对 attributes/condition 的字段类型、比较方式及原文引用。"
        "availability_start 的年月必须在属性 quote 中明确出现；暑期、寒假、下周等不能猜成具体月份，"
        "无法确定就删除该属性，保留原始安排证据。属性引用必须属于该事实的 evidence_ids。"
    ),
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
