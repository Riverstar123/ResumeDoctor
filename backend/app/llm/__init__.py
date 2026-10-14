"""M5 模型网关与受控模型目录。

导入本包不会读取 settings、不会连接任何外部服务；fake 模式不需要 API key。
真实适配器与 `backend/config/models.yaml` 由 AI-02 交付。
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
from .errors import GatewayError
from .gateway import (
    BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    INPUT_LIMITS,
    RETRY_BUDGET,
    FakeModelGateway,
    GatewayCall,
)

__all__ = [
    "BACKOFF_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "GATEWAY_CONFIG_VERSION",
    "GatewayCall",
    "GatewayError",
    "INPUT_LIMITS",
    "PROMPT_VERSIONS",
    "RETRY_BUDGET",
    "TASK_NAMES",
    "FakeModelDirectory",
    "FakeModelGateway",
    "ModelDirectory",
    "ModelEntry",
    "default_fake_entries",
]
