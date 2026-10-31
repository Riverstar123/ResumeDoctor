"""AI-03: business_modules real-mode assembly (composition root only).

The real branch wires build_llm's catalog/gateway and the QA-02-reviewed
privacy filters. No network is used: building the OpenAI-compatible gateway
does not call the provider, and injection is supported for test doubles.
"""

from app.intake.privacy import filter_fake_context
from app.llm import FakeModelDirectory, OpenAICompatibleGateway
from app.reporting.privacy import filter_report_context
from app.runtime import business_modules
from app.settings import Settings


def _real_settings(**overrides) -> Settings:
    values = dict(
        llm_mode="real",
        llm_provider="openai_compatible",
        llm_model="actual-default-model",
        llm_model_a="actual-model-a",
        llm_model_b="actual-model-b",
        llm_base_url="https://api.example.test/v1",
        llm_api_key="test-secret",
        database_url="postgresql://user:pass@localhost:5432/rd_assembly_test",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


class _StubGateway:
    is_fake = False


def test_real_mode_builds_openai_gateway_without_calling_provider() -> None:
    modules = business_modules(_real_settings())
    assert isinstance(modules.gateway, OpenAICompatibleGateway)
    assert modules.intake_privacy_filter is filter_fake_context
    assert modules.reporting._privacy_filter is filter_report_context
    assert modules.scoring is not None


def test_intake_for_wires_reviewed_filter_and_source() -> None:
    modules = business_modules(_real_settings())
    intake = modules.intake_for("doc-123")
    assert intake._privacy_filter is filter_fake_context
    assert intake._source_id == "doc-123"


def test_real_mode_accepts_injected_directory_and_gateway() -> None:
    gateway = _StubGateway()
    directory = FakeModelDirectory()
    modules = business_modules(_real_settings(), directory=directory, gateway=gateway)
    assert modules.gateway is gateway
    assert modules.catalog.directory is directory
    assert modules.reporting._privacy_filter is filter_report_context


def test_fake_mode_assembly_remains_unchanged() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x/y_test")
    modules = business_modules(settings)
    assert modules.intake_privacy_filter is None
    intake = modules.intake_for("msg-1")
    assert intake._privacy_filter is None
    assert intake._source_id == "msg-1"
