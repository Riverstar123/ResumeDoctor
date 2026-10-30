"""AI-03 review item 1: real-mode HTTP startup regression.

Before the fix, app.database.create_app(real settings) failed inside
app.main.create_app's unconditional fake-only gate, so the delivered real
assembly could never start (reproduced by A at construction time). These
tests need no key, database or network: repository is injected as a stub and
the provider is never called at assembly.
"""

import pytest
from fastapi.testclient import TestClient

from app.database import create_app as create_database_app
from app.settings import Settings


class _StubRepository:
    """Construction and this test never invoke real repository methods."""

    def close(self) -> None:
        pass


def real_settings(**overrides) -> Settings:
    values = dict(
        _env_file=None,
        llm_mode="real",
        llm_provider="openai_compatible",
        llm_base_url="https://api.deepseek.test/v1",
        llm_api_key="test-secret",
        llm_model="actual-default-model",
        llm_model_a="actual-other-model",
        database_url="postgresql://user:pass@localhost:5432/rd_startup_test",
        allowed_origins=["http://127.0.0.1:5200"],
    )
    values.update(overrides)
    return Settings(**values)


def test_database_create_app_with_real_settings_starts() -> None:
    app = create_database_app(real_settings(), repository=_StubRepository())
    assert app.state.settings.llm_mode == "real"

    # HTTP startup layer: lifespan boots and the liveness route answers
    # without touching PostgreSQL or the provider.
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_factory_still_rejects_real_settings() -> None:
    # API-01 default all-double factory keeps its fake-only boundary.
    from app.main import create_app

    with pytest.raises(ValueError, match="LLM_MODE=fake"):
        create_app(real_settings())


def test_int01_factory_still_rejects_real_settings() -> None:
    # INT-01 light synthetic root (platform=None, individual injection) is
    # also deliberately kept fake-only.
    from app.integration import create_app

    with pytest.raises(ValueError, match="LLM_MODE=fake"):
        create_app(real_settings())
