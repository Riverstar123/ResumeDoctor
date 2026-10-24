"""Explicit settings loading; creating settings does not connect to external services."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # 真实模式必须显式填写实际模型名；fake 模式不读取该值。
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model_a: str = ""
    llm_model_b: str = ""
    database_url: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    upload_dir: Path = Path("uploads")
    allowed_origins: list[str] = ["http://localhost:5173"]
    session_ttl_days: int = Field(default=7, ge=7, le=7)
    session_cookie_secure: bool = False

    @field_validator("allowed_origins")
    @classmethod
    def fixed_origins(cls, origins: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        if not origins:
            raise ValueError("at least one fixed origin is required")
        for origin in origins:
            url = urlsplit(origin)
            if (
                "*" in origin
                or url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("origins must be fixed HTTP(S) origins without a path")
        return origins


def load_settings() -> Settings:
    return Settings()
