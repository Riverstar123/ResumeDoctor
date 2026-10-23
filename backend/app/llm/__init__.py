"""M5 模型网关与受控模型目录。

导入本包不会读取 settings、不会连接任何外部服务；fake 模式不需要 API key，
也不会读取真实模型目录。`build_llm(settings)` 按 `LLM_MODE` 装配，默认 fake；
`LLM_MODE=real` 时使用 `backend/config/models.yaml` 与 OpenAI-compatible 适配器。
"""

from .catalog import (
    GATEWAY_CONFIG_VERSION,
    PROMPT_VERSIONS,
    TASK_NAMES,
    FakeModelDirectory,
    ModelDirectory,
    ModelEntry,
    default_fake_entries,
)
from .config import (
    DEFAULT_CONFIG_PATH,
    OPENAI_COMPATIBLE,
    CatalogConfig,
    CatalogEntryConfig,
    ConfigModelDirectory,
    ConfiguredModelEntry,
    LLMComponents,
    ModelConnection,
    build_llm,
    configured_directory,
    load_model_config,
)
from .errors import GatewayError
from .gateway import (
    BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    INPUT_LIMITS,
    RETRY_BUDGET,
    FakeModelGateway,
    GatewayCall,
    append_call,
    count_input_chars,
    utc_now,
)
from .openai_compatible import OpenAICompatibleGateway
from .schemas import (
    TASK_OUTPUT_DTOS,
    TASK_OUTPUT_SCHEMAS,
    ChatOutput,
    schema_matches_task,
    task_output_schema,
)

__all__ = [
    "BACKOFF_SECONDS",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_TIMEOUT_SECONDS",
    "GATEWAY_CONFIG_VERSION",
    "INPUT_LIMITS",
    "OPENAI_COMPATIBLE",
    "PROMPT_VERSIONS",
    "RETRY_BUDGET",
    "TASK_NAMES",
    "TASK_OUTPUT_DTOS",
    "TASK_OUTPUT_SCHEMAS",
    "CatalogConfig",
    "CatalogEntryConfig",
    "ChatOutput",
    "ConfigModelDirectory",
    "ConfiguredModelEntry",
    "FakeModelDirectory",
    "FakeModelGateway",
    "GatewayCall",
    "GatewayError",
    "LLMComponents",
    "ModelConnection",
    "ModelDirectory",
    "ModelEntry",
    "OpenAICompatibleGateway",
    "append_call",
    "build_llm",
    "configured_directory",
    "count_input_chars",
    "default_fake_entries",
    "load_model_config",
    "schema_matches_task",
    "task_output_schema",
    "utc_now",
]
