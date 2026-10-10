"""Explicit settings loading; creating settings does not connect to external services."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
    )

    llm_mode: Literal["fake", "real"] = "fake"
    llm_provider: str = "fake"
    llm_model: str = "fake-default"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model_a: str = ""
    llm_model_b: str = ""
    database_url: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    upload_dir: Path = Path("uploads")
    allowed_origins: list[str] = ["http://localhost:5173"]
    session_ttl_days: int = Field(default=7, ge=7, le=7)


def load_settings() -> Settings:
    return Settings()
