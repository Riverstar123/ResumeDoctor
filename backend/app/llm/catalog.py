"""受控模型目录：公开元信息、能力筛选与 model_id → 实际模型映射。

设计对应 [10-model-configuration.md](../../../docs/10-model-configuration.md)：
目录保存公开 id、显示名、provider、能力和实际模型名；**目录里不放任何密钥或端点**。
`GET /models` 的公开 DTO（[Model/ModelList](../../contracts/models.py)）天然不含
key/base_url，因此本模块返回的对象不会泄露凭证。

AI-01 只交付 fake 目录；真实条目从 `backend/config/models.yaml` 读取由 AI-02 实现。
`resolve(model_id, capability, now)` 与 M2 的 `ModelCatalog` 端口同形，便于 #13 注入。
"""

from dataclasses import dataclass
from typing import Protocol

from app.contracts import Model, ModelList, ModelMetadata

from .errors import GatewayError

# 四类任务名同时就是能力名（06-ai-contract.md「四类调用」）。
TASK_NAMES: tuple[str, ...] = (
    "profile_extract",
    "profile_chat",
    "job_extract",
    "diagnosis_report",
)
# 提示词版本由内容负责人维护；报告为 M5，其余为 M3。
PROMPT_VERSIONS: dict[str, str] = {
    "profile_extract": "profile-v1",
    "profile_chat": "chat-v1",
    "job_extract": "job-v1",
    "diagnosis_report": "report-v1",
}
GATEWAY_CONFIG_VERSION = "fake-gateway-v1"


@dataclass(frozen=True)
class ModelEntry:
    """目录条目；`model` 是实际模型名，fake 时明确标识为合成来源。"""

    id: str
    display_name: str
    provider: str
    model: str
    capabilities: tuple[str, ...]
    enabled: bool = True


class ModelDirectory(Protocol):
    def list_models(self) -> ModelList: ...

    def resolve(self, model_id: str, capability: str, now: str) -> ModelMetadata: ...


def _fake_entry(model_id: str) -> ModelEntry:
    return ModelEntry(
        id=model_id,
        display_name=f"演示数据 / {model_id}",
        provider="fake",
        model="synthetic-fake-v1",
        capabilities=TASK_NAMES,
    )


def default_fake_entries() -> tuple[ModelEntry, ModelEntry]:
    """两个明确标识 fake 的条目；默认条目为 demo-model-a。

    沿用 API-01 的 id，避免 B 的前端与已有样例在 #13 集成时改变。
    """
    return _fake_entry("demo-model-a"), _fake_entry("demo-model-b")


class FakeModelDirectory:
    """可注入的假目录；`disabled` 来自服务端，不从用户输入读取。"""

    is_fake = True

    def __init__(
        self,
        entries: tuple[ModelEntry, ...] | None = None,
        default_model_id: str | None = None,
    ):
        self.entries = entries if entries is not None else default_fake_entries()
        self.default_model_id = default_model_id or self.entries[0].id
        self.disabled: set[str] = set()

    def disable(self, model_id: str) -> None:
        self.disabled.add(model_id)

    def _available(self) -> list[ModelEntry]:
        return [entry for entry in self.entries if entry.enabled and entry.id not in self.disabled]

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
            raise GatewayError("MODEL_UNAVAILABLE", "默认模型不可用")
        return ModelList(default_model_id=self.default_model_id, items=items)

    def resolve(self, model_id: str, capability: str, now: str) -> ModelMetadata:
        if capability not in PROMPT_VERSIONS:
            raise GatewayError("MODEL_UNAVAILABLE", f"未知能力或任务：{capability}")
        entry = next((item for item in self._available() if item.id == model_id), None)
        if entry is None:
            raise GatewayError("MODEL_UNAVAILABLE", "模型不存在或已停用")
        if capability not in entry.capabilities:
            raise GatewayError("MODEL_UNAVAILABLE", "模型不支持此任务能力")
        return ModelMetadata(
            model_id=entry.id,
            provider=entry.provider,
            model=entry.model,
            prompt_version=PROMPT_VERSIONS[capability],
            gateway_config_version=GATEWAY_CONFIG_VERSION,
            generated_at=now,
        )
