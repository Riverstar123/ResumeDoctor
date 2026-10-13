"""Wire DTOs for the checked-in OpenAPI; business validation belongs to module owners."""

import json
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field


def _unique(values: Any) -> Any:
    if not isinstance(values, list):
        return values  # Let the normal list validator report the shape error.
    keys = [json_key(value) for value in values]
    if len(set(keys)) != len(keys):
        raise ValueError("items must be unique")
    return values


def json_key(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    def normalize(item: Any) -> Any:
        if type(item) is float and math.isfinite(item) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {k: normalize(v) for k, v in item.items()}
        if isinstance(item, list):
            return [normalize(v) for v in item]
        return item

    return json.dumps(normalize(value), sort_keys=True, ensure_ascii=False)


def _integer(value: Any) -> Any:
    # JSON Schema counts integral JSON numbers (e.g. 1.0) as integers.
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    if type(value) is not int:
        raise ValueError("expected an integer, not a boolean or coercible string")
    return value


def _number(value: Any) -> Any:
    if type(value) not in (int, float):
        raise ValueError("expected a JSON number")
    return value


def _datetime(value: str) -> str:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value.upper(),
    ):
        raise ValueError("expected an RFC 3339 date-time with an offset")
    datetime.fromisoformat(value.upper())
    return value


def _uuid(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("expected a hyphenated UUID string")
    return value


# Preserve wire strings, including UUID casing, rather than normalizing array items.
UUIDValue = Annotated[str, AfterValidator(_uuid), Field(json_schema_extra={"format": "uuid"})]
DateTimeValue = Annotated[
    str, AfterValidator(_datetime), Field(json_schema_extra={"format": "date-time"})
]
JSONInteger = Annotated[int, BeforeValidator(_integer)]
PositiveJSONInteger = Annotated[int, Field(ge=1), BeforeValidator(_integer)]


class ContractDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ErrorInfo(ContractDTO):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Error(ContractDTO):
    error: ErrorInfo
    request_id: str


class Session(ContractDTO):
    id: UUIDValue
    expires_at: DateTimeValue


class Model(ContractDTO):
    id: str = Field(min_length=1, max_length=100)
    display_name: str
    provider: str
    capabilities: list[
        Literal["profile_extract", "profile_chat", "job_extract", "diagnosis_report"]
    ] = Field(min_length=1)


class ModelList(ContractDTO):
    default_model_id: str = Field(min_length=1, max_length=100)
    items: list[Model] = Field(min_length=1)


class Evidence(ContractDTO):
    id: str = Field(min_length=1)
    source_type: Literal["document", "message", "manual"]
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    locator: str | None


class Fact(ContractDTO):
    id: str = Field(min_length=1)
    kind: Literal["skill", "experience", "education", "project"]
    label: str = Field(min_length=1)
    value: str | None
    polarity: Literal["positive", "negative"]
    application: Literal["applied", "claimed"]
    start_month: str | None = Field(pattern="^\\d{4}-(0[1-9]|1[0-2])$")
    end_month: str | None = Field(pattern="^\\d{4}-(0[1-9]|1[0-2])$")
    completed: bool | None
    evidence_ids: Annotated[list[str], BeforeValidator(_unique)] = Field(
        min_length=1, json_schema_extra={"uniqueItems": True}
    )


class ProfileContent(ContractDTO):
    overview: str = Field(max_length=8000)
    as_of_month: str = Field(pattern="^\\d{4}-(0[1-9]|1[0-2])$")
    facts: list[Fact] = Field(max_length=100)
    evidence: list[Evidence] = Field(max_length=200)


class Profile(ContractDTO):
    id: UUIDValue
    version: JSONInteger = Field(ge=1)
    confirmed: bool
    content: ProfileContent
    created_at: DateTimeValue


class ProfileCreate(ContractDTO):
    content: ProfileContent


class ProfileUpdate(ContractDTO):
    base_version: JSONInteger = Field(ge=1)
    content: ProfileContent


class Requirement(ContractDTO):
    id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    category: Literal["skill", "experience", "education", "project", "other"]
    importance: Literal["must", "preferred"]
    operator: Literal["has_skill", "min_months", "degree_at_least", "has_evidence", "manual_review"]
    target: str = Field(min_length=1)
    ignored: bool
    ignore_reason: str | None
    subject: str | None


class JobContent(ContractDTO):
    title: str = Field(min_length=1, max_length=200)
    company_name: str | None
    company_context: str = Field(max_length=10000)
    requirements: list[Requirement] = Field(max_length=100)


class Job(ContractDTO):
    id: UUIDValue
    version: JSONInteger = Field(ge=1)
    confirmed: bool
    raw_text: str = Field(min_length=1, max_length=20000)
    content: JobContent
    created_at: DateTimeValue


class JobCreate(ContractDTO):
    raw_text: str = Field(min_length=1, max_length=20000)
    company_context: str = Field(max_length=10000)
    model_id: str = Field(min_length=1, max_length=100)


class JobUpdate(ContractDTO):
    base_version: JSONInteger = Field(ge=1)
    raw_text: str = Field(min_length=1, max_length=20000)
    content: JobContent


class Confirmation(ContractDTO):
    version: JSONInteger = Field(ge=1)


class MessageCreate(ContractDTO):
    base_version: JSONInteger = Field(ge=1)
    content: str = Field(min_length=1, max_length=8000)
    model_id: str = Field(min_length=1, max_length=100)


class Message(ContractDTO):
    id: UUIDValue
    role: Literal["user", "assistant"]
    content: str
    created_at: DateTimeValue


class MessageList(ContractDTO):
    items: list[Message] = Field(max_length=100)


class TaskAccepted(ContractDTO):
    task_id: UUIDValue


class DiagnosisAccepted(ContractDTO):
    task_id: UUIDValue
    diagnosis_id: UUIDValue


class ResourceVersion(ContractDTO):
    id: UUIDValue
    version: JSONInteger = Field(ge=1)


class DiagnosisCreate(ContractDTO):
    profile: ResourceVersion
    jobs: Annotated[list[ResourceVersion], BeforeValidator(_unique)] = Field(
        min_length=1, max_length=5, json_schema_extra={"uniqueItems": True}
    )
    model_id: str = Field(min_length=1, max_length=100)


class TaskResult(ContractDTO):
    resource_type: Literal["profile", "job", "diagnosis"]
    resource_id: UUIDValue
    version: PositiveJSONInteger | None
    assistant_message: str | None


class Task(ContractDTO):
    id: UUIDValue
    kind: Literal["document_parse", "profile_chat", "job_parse", "diagnosis"]
    status: Literal["queued", "running", "succeeded", "partial", "failed"]
    model_id: str = Field(min_length=1, max_length=100)
    result: TaskResult | None
    error: ErrorInfo | None
    created_at: DateTimeValue
    updated_at: DateTimeValue


class RequirementAssessment(ContractDTO):
    requirement_id: str
    category: Literal["skill", "experience", "education", "project", "other"]
    importance: Literal["must", "preferred"]
    status: Literal["met", "partial", "unmet", "unknown"]
    weight: Annotated[Literal[1, 2], BeforeValidator(_integer)] = Field(
        json_schema_extra={"type": "integer"}
    )
    coefficient: Annotated[Literal[0, 0.5, 1], BeforeValidator(_number)] = Field(
        json_schema_extra={"type": "number"}
    )
    evidence_ids: Annotated[list[str], BeforeValidator(_unique)] = Field(
        json_schema_extra={"uniqueItems": True}
    )
    reason: str = Field(min_length=1)


class DimensionScore(ContractDTO):
    category: Literal["skill", "experience", "education", "project", "other"]
    score: float = Field(ge=0, le=100)


class ScoreResult(ContractDTO):
    score: float = Field(ge=0, le=100)
    unknown_weight_ratio: float = Field(ge=0, le=1)
    rule_version: str
    matcher_version: str
    assessments: list[RequirementAssessment] = Field(min_length=1)
    dimensions: list[DimensionScore] = Field(min_length=1)


class Gap(ContractDTO):
    requirement_id: str
    kind: Literal["explicit_gap", "partial_gap", "needs_evidence"]
    description: str
    evidence_ids: Annotated[list[str], BeforeValidator(_unique)] = Field(
        json_schema_extra={"uniqueItems": True}
    )


class Suggestion(ContractDTO):
    requirement_id: str
    original: str | None
    revised: str
    rationale: str
    evidence_ids: Annotated[list[str], BeforeValidator(_unique)] = Field(
        json_schema_extra={"uniqueItems": True}
    )
    requires_user_input: bool


class Action(ContractDTO):
    requirement_id: str
    priority: Literal["P0", "P1", "P2"]
    horizon: Literal["now", "next_2_weeks", "next_2_months"]
    task: str
    done_when: str


class ReportContent(ContractDTO):
    summary: str
    gaps: list[Gap]
    suggestions: list[Suggestion]
    actions: list[Action]


class ModelMetadata(ContractDTO):
    model_id: str = Field(min_length=1, max_length=100)
    provider: str
    model: str
    prompt_version: str
    gateway_config_version: str
    generated_at: DateTimeValue


class DiagnosisItem(ContractDTO):
    id: UUIDValue
    job: ResourceVersion
    status: Literal["pending", "scoring", "reporting", "succeeded", "score_only", "failed"]
    score_result: ScoreResult | None
    report: ReportContent | None
    error: ErrorInfo | None
    model_metadata: ModelMetadata | None


class Diagnosis(ContractDTO):
    id: UUIDValue
    task_id: UUIDValue
    status: Literal["queued", "running", "succeeded", "partial", "failed"]
    profile: ResourceVersion
    model_id: str = Field(min_length=1, max_length=100)
    items: list[DiagnosisItem] = Field(min_length=1, max_length=5)
    created_at: DateTimeValue


class SessionCreate(ContractDTO):
    consent_version: Literal["v1"]


SCHEMA_MODELS = {
    "ErrorInfo": ErrorInfo,
    "Error": Error,
    "Session": Session,
    "Model": Model,
    "ModelList": ModelList,
    "Evidence": Evidence,
    "Fact": Fact,
    "ProfileContent": ProfileContent,
    "Profile": Profile,
    "ProfileCreate": ProfileCreate,
    "ProfileUpdate": ProfileUpdate,
    "Requirement": Requirement,
    "JobContent": JobContent,
    "Job": Job,
    "JobCreate": JobCreate,
    "JobUpdate": JobUpdate,
    "Confirmation": Confirmation,
    "MessageCreate": MessageCreate,
    "Message": Message,
    "MessageList": MessageList,
    "TaskAccepted": TaskAccepted,
    "DiagnosisAccepted": DiagnosisAccepted,
    "ResourceVersion": ResourceVersion,
    "DiagnosisCreate": DiagnosisCreate,
    "TaskResult": TaskResult,
    "Task": Task,
    "RequirementAssessment": RequirementAssessment,
    "DimensionScore": DimensionScore,
    "ScoreResult": ScoreResult,
    "Gap": Gap,
    "Suggestion": Suggestion,
    "Action": Action,
    "ReportContent": ReportContent,
    "ModelMetadata": ModelMetadata,
    "DiagnosisItem": DiagnosisItem,
    "Diagnosis": Diagnosis,
}
