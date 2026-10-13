import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_fake_template_loads_with_blank_keys():
    from pathlib import Path

    settings = Settings(_env_file=Path(__file__).resolve().parents[1] / ".env.example")
    assert settings.llm_mode == "fake"
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.database_url.get_secret_value() == ""
    assert settings.session_ttl_days == 7


def test_secrets_are_redacted_and_settings_are_loaded_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "real")
    env = tmp_path / "config.env"
    env.write_text("LLM_API_KEY=synthetic-config-test\n")
    settings = Settings(_env_file=env)
    assert "synthetic-config-test" not in repr(settings)
    assert settings.llm_mode == "real"
    monkeypatch.setenv("LLM_MODE", "fake")
    assert Settings(_env_file=None).llm_mode == "fake"


def test_bad_mode_and_changed_session_lifetime_are_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_mode="invalid")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, session_ttl_days=14)


def test_contracts_and_factory_import_without_settings_or_network(tmp_path):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}
    environment["LLM_MODE"] = "invalid-import-must-not-read-this"
    script = """
import socket
def forbidden(*args, **kwargs):
    raise AssertionError('network connection during import')
socket.socket.connect = forbidden
socket.create_connection = forbidden
from app.contracts import ProfileContent, JobContent, ScoreResult, ReportContent
from app.contracts.ports import IntakePort, ScoringPort, ReportingPort, ModelGateway, TaskContext
from app.main import create_app
assert TaskContext('fake-test').model_id == 'fake-test'
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
