"""Private two-stage generation contract; not an HTTP or model-directory capability."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import GatewayError


@dataclass(frozen=True)
class ReviewRequest:
    """Review the frozen candidate without permitting the reviewer to rewrite it."""

    prompt_context: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    validate_output: Callable[[Mapping[str, Any]], None]
    reject_if_declined: Callable[[Mapping[str, Any]], None] | None = None
    max_output_tokens: int = 8192
    finalize_candidate: (
        Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None


class ReviewRejected(GatewayError):
    """A substantive rejection is final, never retried to obtain a different verdict."""

    def __init__(self, *, reason_code: str = "REPORT_REVIEW_INVALID", issues=()):
        super().__init__(
            "MODEL_OUTPUT_INVALID",
            "报告未通过独立证据核对，已保留规则评分。",
            reason_code=reason_code,
            issues=issues,
        )
