"""Shared scope, cache identity and immutable-base merge for optional advice."""

import hashlib
import json

from app.contracts import ReportContent
from app.platform.errors import PlatformError
from app.platform.validation import invalid
from app.reporting.enhancement import ENHANCEMENT_POLICY_VERSION

BASE_TEMPLATE_VERSION = "base-report-v1"
RULES_EXECUTOR = "rules"


def scope_for(item, job, requested):
    if item.report_template_version != BASE_TEMPLATE_VERSION:
        raise PlatformError(
            409, "LEGACY_REPORT_REQUIRES_BASE", "此历史报告使用旧流程，请先用原快照生成基础报告"
        )
    if item.score_result is None or item.report is None or item.status != "succeeded":
        raise invalid()
    allowed = {r.id for r in job.content.requirements if not r.ignored}
    if not set(requested) <= allowed:
        raise invalid()
    return sorted(requested or allowed)


def identity(item_id, scope, metadata):
    # generated_at changes on every request and is deliberately not part of identity.
    model = metadata.model_dump(mode="json", exclude={"generated_at"})
    return hashlib.sha256(
        json.dumps([item_id, scope, model, ENHANCEMENT_POLICY_VERSION], sort_keys=True).encode()
    ).hexdigest()


def merge_advice(base, candidate):
    if candidate.summary != base.summary or candidate.gaps != base.gaps:
        raise ValueError("Enhancement may not change frozen base explanation")
    result = base.model_copy(deep=True)
    for name in ("suggestions", "actions"):
        incoming = getattr(candidate, name)
        replaced = {item.requirement_id for item in incoming}
        setattr(
            result,
            name,
            [item for item in getattr(base, name) if item.requirement_id not in replaced]
            + incoming,
        )
    return ReportContent.model_validate(result.model_dump(mode="json"))


def validate_candidate(candidate, profile, job, score, scope):
    from app.reporting.validation import validate_report

    validate_report(candidate, profile.content, job.content, score)
    if any(i.requirement_id not in scope for i in [*candidate.suggestions, *candidate.actions]):
        raise ValueError("Advice escaped requested requirements")
