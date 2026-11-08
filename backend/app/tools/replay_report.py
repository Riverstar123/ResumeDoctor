"""Offline replay of saved report responses. No provider client or network calls.

Example: python -m app.tools.replay_report --profile profile.json --job job.json
  --diagnosis diagnosis.json --candidate response.json --response-mode deepseek_strict
  [--review review.json]
Use --show-excerpts only with authorized local test data; server logs omit prose.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from app.contracts import Diagnosis, Job, Profile, ReportContent
from app.diagnostics import locate, output_issues, pydantic_issues
from app.llm.errors import GatewayError
from app.llm.openai_compatible import _InvalidOutput, extract_content, unique_object
from app.reporting import ReportService, validate_report
from app.reporting.explanation import assemble_report
from app.reporting.grounding import build_grounding_review
from app.reporting.privacy import filter_report_context

RESPONSE_MODES = ("json_object", "deepseek_strict")


def payload(value, *, response_mode=None):
    envelope = isinstance(value, dict) and "choices" in value
    if response_mode not in (None, *RESPONSE_MODES) or envelope and response_mode is None:
        raise GatewayError(
            "MODEL_OUTPUT_INVALID",
            "供应商响应回放须显式指定原请求的结构输出模式",
            reason_code="SCHEMA_INVALID",
            issues=(
                locate(
                    ("response_mode",),
                    "REPLAY_MODE_REQUIRED" if response_mode is None else "REPLAY_MODE_INVALID",
                ),
            ),
        )
    if envelope:
        try:
            return json.loads(
                extract_content(value, strict=response_mode == "deepseek_strict"),
                object_pairs_hook=unique_object,
            )
        except ValueError:
            raise GatewayError(
                "MODEL_OUTPUT_INVALID",
                "响应 JSON 无效",
                reason_code="JSON_INVALID",
                issues=(locate((), "JSON_PARSE"),),
            ) from None
        except _InvalidOutput as error:
            raise GatewayError(
                "MODEL_OUTPUT_INVALID",
                "响应封装未通过校验",
                reason_code=error.reason_code,
                issues=error.issues,
            ) from None

    return value


def replay(
    profile,
    job,
    score,
    candidate,
    *,
    review=None,
    assemble_advice=False,
    excerpts=False,
    response_mode=None,
):
    result = {
        "mode": "offline",
        "response_mode": response_mode,
        "deterministic": "NOT_RUN",
        "semantic": "NOT_RUN",
    }
    stage = "provider_response"
    try:
        candidate = payload(candidate, response_mode=response_mode)
        stage = "report_schema"
        if assemble_advice:
            candidate = assemble_report(
                ReportService._limit_optional_items(
                    {k: candidate[k] for k in ("suggestions", "actions")},
                    supported_facts_only=score.rule_version != "coverage-v1",
                ),
                score,
            )
        report = ReportContent.model_validate(candidate)
        stage = "report_business"
        validate_report(report, profile.content, job.content, score)
        result["deterministic"] = "PASS"
        if review is not None:
            stage = "report_review"
            sent = filter_report_context(ReportService._prompt_context(profile, job, score))
            build_grounding_review(report.model_dump(mode="json"), sent).validate_output(
                payload(review, response_mode=response_mode)
            )
            result["semantic"] = "RECORDED_VERDICT_ACCEPTED"
    except (GatewayError, ValueError, KeyError, TypeError) as error:
        result["failed_stage"] = stage
        result["semantic" if stage == "report_review" else "deterministic"] = "FAIL"
        result["reason_code"] = getattr(error, "reason_code", "SCHEMA_INVALID")
        issues = (
            pydantic_issues(error) if isinstance(error, ValidationError) else output_issues(error)
        )
        result["issues"] = [asdict(i) for i in issues or (locate((), "REPLAY_INVALID"),)]
        if excerpts:
            for issue in result["issues"]:
                value = candidate
                try:
                    for part in issue["path"].strip("/").split("/"):
                        value = value[int(part)] if isinstance(value, list) else value[part]
                    if isinstance(value, str):
                        start, end = issue["start"], issue["end"]
                        issue["local_excerpt"] = (
                            value[start:end][:200] if start is not None else value[:200]
                        )
                except (KeyError, TypeError, IndexError, ValueError):
                    pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("profile", "job", "diagnosis", "candidate"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument(
        "--response-mode",
        choices=RESPONSE_MODES,
        help="Original request mode; required for provider envelopes, never inferred from responses",
    )
    parser.add_argument("--assemble-advice", action="store_true")
    parser.add_argument("--show-excerpts", action="store_true")
    args = parser.parse_args()

    def read(p):
        return json.loads(p.read_text(), object_pairs_hook=unique_object)

    profile = Profile.model_validate(read(args.profile))
    job = Job.model_validate(read(args.job))
    diagnosis = Diagnosis.model_validate(read(args.diagnosis))
    item = next(i for i in diagnosis.items if i.job.id == job.id and i.job.version == job.version)
    if item.score_result is None:
        parser.error("saved diagnosis has no score")
    print(
        json.dumps(
            replay(
                profile,
                job,
                item.score_result,
                read(args.candidate),
                review=read(args.review) if args.review else None,
                assemble_advice=args.assemble_advice,
                excerpts=args.show_excerpts,
                response_mode=args.response_mode,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
