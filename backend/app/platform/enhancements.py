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


def merge_advice(base, candidate, scope=None):
    result = base.model_copy(deep=True)
    result.summary = candidate.summary
    for name in ("gaps", "suggestions", "actions"):
        incoming = getattr(candidate, name)
        replaced = set(scope) if scope is not None else {item.requirement_id for item in incoming}
        setattr(
            result,
            name,
            [item for item in getattr(base, name) if item.requirement_id not in replaced]
            + incoming,
        )
    return ReportContent.model_validate(result.model_dump(mode="json"))


def validate_candidate(candidate, profile, job, score, scope):
    # Referential integrity only. User-facing analysis is authored by the model;
    # it is not required to agree with deterministic scoring.
    ReportContent.model_validate(candidate.model_dump(mode="json"))
    evidence_ids = {e.id for e in profile.content.evidence}
    for entry in [*candidate.gaps, *candidate.suggestions, *candidate.actions]:
        if entry.requirement_id not in scope:
            raise ValueError("Advice escaped requested requirements")
        if not set(getattr(entry, "evidence_ids", [])) <= evidence_ids:
            raise ValueError("Unknown evidence reference")
