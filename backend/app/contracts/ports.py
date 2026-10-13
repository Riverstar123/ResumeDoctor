"""Injectable internal ports. These are contracts, not business implementations.

Async ports handle input/model I/O. M4 scoring and Markdown export are synchronous.
The caller owns the borrowed stream and all persistence/HTTP/session decisions.
"""

from dataclasses import dataclass
from typing import Any, BinaryIO, Literal, Mapping, Protocol, Sequence, runtime_checkable

from app.contracts.models import (
    DiagnosisItem,
    Job,
    JobContent,
    Message,
    ModelMetadata,
    Profile,
    ProfileContent,
    ReportContent,
    RequirementAssessment,
    ScoreResult,
)


@dataclass(frozen=True)
class TaskContext:
    """The caller's frozen model selection; no credentials or provider clients."""

    model_id: str


@dataclass(frozen=True)
class TextSegment:
    text: str
    locator: str | None


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    segments: tuple[TextSegment, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ConversationResult:
    assistant_message: str
    profile_content: ProfileContent


@dataclass(frozen=True)
class StructuredResult:
    data: Mapping[str, Any]
    model_metadata: ModelMetadata


@runtime_checkable
class IntakePort(Protocol):
    async def extract_document(self, handle: BinaryIO, media_type: str) -> ExtractedDocument: ...

    async def build_profile(
        self,
        text: str,
        source_type: Literal["document", "message", "manual"],
        previous_profile: Profile | None = None,
        *,
        context: TaskContext,
    ) -> ProfileContent: ...

    async def advance_conversation(
        self,
        user_text: str,
        profile_content: ProfileContent,
        history_user_messages: Sequence[Message],
        *,
        context: TaskContext,
    ) -> ConversationResult: ...

    async def extract_job(
        self,
        raw_text: str,
        company_context: str,
        *,
        context: TaskContext,
    ) -> JobContent: ...


@runtime_checkable
class ScoringPort(Protocol):
    def assess_requirements(
        self,
        profile_content: ProfileContent,
        job_content: JobContent,
        matcher_version: str,
    ) -> list[RequirementAssessment]: ...

    def calculate_score(
        self,
        assessments: Sequence[RequirementAssessment],
        rule_version: str,
    ) -> ScoreResult: ...


@runtime_checkable
class ReportingPort(Protocol):
    async def generate_report(
        self,
        profile_snapshot: Profile,
        job_snapshot: Job,
        score_result: ScoreResult,
        model_metadata: ModelMetadata,
        *,
        context: TaskContext,
    ) -> ReportContent: ...

    def export_markdown(self, item: DiagnosisItem) -> str: ...


@runtime_checkable
class ModelGateway(Protocol):
    async def generate_structured(
        self,
        task_name: str,
        prompt_context: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        timeout_seconds: float,
        *,
        context: TaskContext,
    ) -> StructuredResult: ...
