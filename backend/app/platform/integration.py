"""P1 assembly adapters; algorithms and extraction remain with their owners.

The report adapter is explicitly fake until RP-01. It consumes E's gateway,
never computes a score, and reuses API-01's synthetic Markdown formatter.
"""

from app.contracts import ReportContent
from app.contracts.ports import ModelGateway
from app.llm import GatewayError, ModelDirectory
from app.platform.errors import PlatformError
from app.platform.fakes import FakeReporting


def gateway_error(exc: GatewayError) -> PlatformError:
    # Provider messages may contain input, URLs or secrets. Only expose known codes.
    code = (
        exc.code
        if exc.code
        in {
            "MODEL_UNAVAILABLE",
            "MODEL_TIMEOUT",
            "MODEL_OUTPUT_INVALID",
            "PROVIDER_UNAVAILABLE",
            "INPUT_TOO_LONG",
        }
        else "INTERNAL_ERROR"
    )
    return PlatformError(
        500 if code == "INTERNAL_ERROR" else 422, code, "演示模型处理失败，请检查配置或重试"
    )


class GatewayCatalog:
    """Translate M5's internal errors at the M2 boundary, including pre-enqueue."""

    def __init__(self, directory: ModelDirectory):
        self.directory = directory

    def list_models(self):
        try:
            return self.directory.list_models()
        except GatewayError as exc:
            raise gateway_error(exc) from None

    def resolve(self, model_id, capability, now):
        try:
            return self.directory.resolve(model_id, capability, now)
        except GatewayError as exc:
            raise gateway_error(exc) from None


class GatewayReporting(FakeReporting):
    """Synthetic report only; this does not deliver RP-01 validation/export."""

    def __init__(self, gateway: ModelGateway, *, timeout_seconds=45.0):
        self.gateway = gateway
        self.timeout_seconds = timeout_seconds

    async def generate_report(
        self, profile_snapshot, job_snapshot, score_result, model_metadata, *, context
    ):
        try:
            result = await self.gateway.generate_structured(
                "diagnosis_report",
                {
                    "profile": profile_snapshot.content.model_dump(mode="json"),
                    "job": job_snapshot.content.model_dump(mode="json"),
                    "score_result": score_result.model_dump(mode="json"),
                },
                ReportContent.model_json_schema(),
                self.timeout_seconds,
                context=context,
            )
        except GatewayError as exc:
            raise gateway_error(exc) from None
        frozen_fields = (
            "model_id",
            "provider",
            "model",
            "prompt_version",
            "gateway_config_version",
        )
        if any(
            getattr(result.model_metadata, key) != getattr(model_metadata, key)
            for key in frozen_fields
        ):
            raise PlatformError(422, "MODEL_UNAVAILABLE", "模型映射已变化，请重新创建任务")
        return ReportContent.model_validate(result.data)
