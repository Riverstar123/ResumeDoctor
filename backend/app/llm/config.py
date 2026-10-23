"""真实模型模式：受控目录 `backend/config/models.yaml` 与 fake/real 装配。

目录只保存公开元信息和环境变量名，**不保存密钥或端点**。运行时由
`build_llm(settings)` 根据 `LLM_MODE` 选择：

- `fake`：沿用 AI-01 的 `FakeModelDirectory` / `FakeModelGateway`，不读 YAML、
  不连接网络；
- `real`：读取 YAML 目录，从服务端 Settings 解析实际模型名、base URL 与密钥，
  构造 `ConfigModelDirectory` 和 OpenAI-compatible 网关。

缺少默认模型所需变量、目录字段非法或 provider 不受支持时，在启动阶段以
`MODEL_UNAVAILABLE` 明确失败，错误信息只包含变量名，不回显密钥或端点。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from app.contracts import Model, ModelList, ModelMetadata
from app.contracts.ports import ModelGateway
from app.settings import Settings

from .catalog import PROMPT_VERSIONS, TASK_NAMES, FakeModelDirectory, ModelDirectory
from .errors import GatewayError
from .gateway import FakeModelGateway

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
OPENAI_COMPATIBLE = "openai_compatible"

# 目录中的环境变量名 → Settings 字段。新增供应商时应先扩展 Settings 与适配器，
# 不能靠任意环境变量绕过服务端配置校验。
_ENV_FIELDS: dict[str, str] = {
    "LLM_MODEL": "llm_model",
    "LLM_MODEL_A": "llm_model_a",
    "LLM_MODEL_B": "llm_model_b",
    "LLM_BASE_URL": "llm_base_url",
    "LLM_API_KEY": "llm_api_key",
}
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class CatalogEntryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    enabled: bool = True
    model_env: str = "LLM_MODEL"
    base_url_env: str = "LLM_BASE_URL"
    api_key_env: str = "LLM_API_KEY"

    @model_validator(mode="after")
    def valid_entry(self) -> "CatalogEntryConfig":
        unknown = sorted(set(self.capabilities) - set(TASK_NAMES))
        if unknown:
            raise ValueError(f"未知能力：{'、'.join(unknown)}")
        for name in (self.model_env, self.base_url_env, self.api_key_env):
            if not _ENV_NAME.match(name):
                raise ValueError(f"环境变量名不合法：{name}")
            if name not in _ENV_FIELDS:
                raise ValueError(f"不支持的环境变量：{name}")
        return self


class CatalogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=100)
    default_model_id: str = Field(min_length=1, max_length=100)
    models: list[CatalogEntryConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_catalog(self) -> "CatalogConfig":
        ids = [entry.id for entry in self.models]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"模型 id 重复：{'、'.join(duplicates)}")
        if self.default_model_id not in ids:
            raise ValueError("default_model_id 不在 models 中")
        if not any(entry.id == self.default_model_id and entry.enabled for entry in self.models):
            raise ValueError("默认模型必须存在且 enabled")
        return self


@dataclass(frozen=True)
class ModelConnection:
    """一次供应商请求所需的服务端连接信息；key 不进入 repr 或公开 DTO。"""

    model: str
    base_url: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class ConfiguredModelEntry:
    id: str
    display_name: str
    provider: str
    capabilities: tuple[str, ...]
    enabled: bool
    model: str = ""
    base_url: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    problem: str | None = None

    @property
    def usable(self) -> bool:
        return self.enabled and self.problem is None


def _format_validation_error(error: ValidationError) -> str:
    """只输出字段位置和原因，不回显 YAML 中的值。"""
    parts = []
    for item in error.errors(include_input=False)[:5]:
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        parts.append(f"{location}: {item['msg']}")
    return "；".join(parts)


def load_model_config(path: Path | str | None = None) -> CatalogConfig:
    """读取并校验受控目录；文件缺失或字段非法时明确失败。"""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw: Any = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError:
        raise GatewayError("MODEL_UNAVAILABLE", f"无法读取模型目录配置：{target}") from None
    except yaml.YAMLError:
        raise GatewayError("MODEL_UNAVAILABLE", f"模型目录配置不是合法 YAML：{target}") from None
    if not isinstance(raw, Mapping):
        raise GatewayError("MODEL_UNAVAILABLE", "模型目录配置必须是 YAML 映射")
    try:
        return CatalogConfig.model_validate(dict(raw))
    except ValidationError as error:
        raise GatewayError(
            "MODEL_UNAVAILABLE", f"模型目录配置无效：{_format_validation_error(error)}"
        ) from None


def _setting_value(settings: Settings, env_name: str) -> str:
    raw = getattr(settings, _ENV_FIELDS[env_name])
    if isinstance(raw, SecretStr):
        raw = raw.get_secret_value()
    return str(raw or "").strip()


def _valid_base_url(value: str) -> bool:
    """只接受固定 HTTP(S) 端点；禁止 userinfo、query 和 fragment。"""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


class ConfigModelDirectory:
    """由 `models.yaml` 解析出的真实模型目录。

    `list_models` 只返回 enabled 且所需变量齐全的条目；默认条目不可用时抛
    `MODEL_UNAVAILABLE`。`connection` 仅供网关读取，公开 DTO 不含端点或密钥。
    """

    is_fake = False

    def __init__(self, version: str, default_model_id: str, entries: list[ConfiguredModelEntry]):
        self.version = version
        self.default_model_id = default_model_id
        self._entries = {entry.id: entry for entry in entries}

    @property
    def entries(self) -> tuple[ConfiguredModelEntry, ...]:
        return tuple(self._entries.values())

    def _available(self) -> list[ConfiguredModelEntry]:
        return [entry for entry in self._entries.values() if entry.usable]

    def list_models(self) -> ModelList:
        items = [
            Model(
                id=entry.id,
                display_name=entry.display_name,
                provider=entry.provider,
                capabilities=list(entry.capabilities),
            )
            for entry in self._available()
        ]
        if not items or self.default_model_id not in {item.id for item in items}:
            default = self._entries.get(self.default_model_id)
            detail = default.problem if default is not None else "条目不存在"
            raise GatewayError(
                "MODEL_UNAVAILABLE",
                f"默认模型 {self.default_model_id} 不可用：{detail}；"
                "请填写 backend/.env 后重启 API 和 worker",
            )
        return ModelList(default_model_id=self.default_model_id, items=items)

    def _usable_entry(self, model_id: str) -> ConfiguredModelEntry:
        entry = self._entries.get(model_id)
        if entry is None or not entry.enabled:
            raise GatewayError("MODEL_UNAVAILABLE", "模型不存在或已停用")
        if not entry.usable:
            raise GatewayError("MODEL_UNAVAILABLE", f"模型 {model_id} 不可用：{entry.problem}")
        return entry

    def resolve(self, model_id: str, capability: str, now: str) -> ModelMetadata:
        if capability not in PROMPT_VERSIONS:
            raise GatewayError("MODEL_UNAVAILABLE", f"未知能力或任务：{capability}")
        entry = self._usable_entry(model_id)
        if capability not in entry.capabilities:
            raise GatewayError("MODEL_UNAVAILABLE", "模型不支持此任务能力")
        return ModelMetadata(
            model_id=entry.id,
            provider=entry.provider,
            model=entry.model,
            prompt_version=PROMPT_VERSIONS[capability],
            gateway_config_version=self.version,
            generated_at=now,
        )

    def connection(self, model_id: str) -> ModelConnection:
        entry = self._usable_entry(model_id)
        return ModelConnection(model=entry.model, base_url=entry.base_url, api_key=entry.api_key)


def configured_directory(config: CatalogConfig, settings: Settings) -> ConfigModelDirectory:
    """把目录条目与服务端变量合并；缺失变量只形成可诊断的不可用条目。"""
    entries: list[ConfiguredModelEntry] = []
    for item in config.models:
        model = _setting_value(settings, item.model_env)
        base_url = _setting_value(settings, item.base_url_env).rstrip("/")
        api_key = _setting_value(settings, item.api_key_env)
        problem: str | None = None
        if item.provider != settings.llm_provider:
            problem = (
                f"条目 provider={item.provider} 与 LLM_PROVIDER={settings.llm_provider} 不一致"
            )
        elif not model:
            problem = f"缺少环境变量 {item.model_env}"
        elif not base_url:
            problem = f"缺少环境变量 {item.base_url_env}"
        elif not api_key:
            problem = f"缺少环境变量 {item.api_key_env}"
        elif not _valid_base_url(base_url):
            problem = f"{item.base_url_env} 必须是固定的 HTTP(S) 地址，且不能包含用户名、查询或片段"
        entries.append(
            ConfiguredModelEntry(
                id=item.id,
                display_name=item.display_name,
                provider=item.provider,
                capabilities=tuple(item.capabilities),
                enabled=item.enabled,
                model=model,
                base_url=base_url,
                api_key=api_key,
                problem=problem,
            )
        )
    return ConfigModelDirectory(config.version, config.default_model_id, entries)


@dataclass(frozen=True)
class LLMComponents:
    directory: ModelDirectory
    gateway: ModelGateway


def build_llm(
    settings: Settings | None = None,
    *,
    config_path: Path | str | None = None,
    transport: Any = None,
) -> LLMComponents:
    """按 `LLM_MODE` 装配目录与网关；默认 fake，绝不隐式发起真实请求。"""
    if settings is None:
        from app.settings import load_settings

        settings = load_settings()

    if settings.llm_mode == "fake":
        directory = FakeModelDirectory()
        return LLMComponents(directory=directory, gateway=FakeModelGateway(directory))

    if settings.llm_provider != OPENAI_COMPATIBLE:
        raise GatewayError(
            "MODEL_UNAVAILABLE",
            f"LLM_MODE=real 目前只支持 LLM_PROVIDER={OPENAI_COMPATIBLE}；其他协议需要独立适配器",
        )

    config = load_model_config(config_path)
    directory = configured_directory(config, settings)
    # 启动时即验证默认模型，避免服务起来了才发现缺配置。
    directory.list_models()

    from .openai_compatible import OpenAICompatibleGateway

    return LLMComponents(
        directory=directory,
        gateway=OpenAICompatibleGateway(directory, transport=transport),
    )
