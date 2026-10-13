"""Injectable public model directory stub; no provider secrets or network clients."""

from typing import Protocol

from app.contracts import Model, ModelList, ModelMetadata
from app.platform.errors import PlatformError


class ModelCatalog(Protocol):
    def list_models(self) -> ModelList: ...

    def resolve(self, model_id: str, capability: str, now: str) -> ModelMetadata: ...


class FakeModelCatalog:
    is_fake = True

    def __init__(self, models: ModelList | None = None):
        self.models = models or ModelList(
            default_model_id="demo-model-a",
            items=[
                Model(
                    id=model_id,
                    display_name=f"演示数据 / {model_id}",
                    provider="fake",
                    capabilities=[
                        "profile_extract",
                        "profile_chat",
                        "job_extract",
                        "diagnosis_report",
                    ],
                )
                for model_id in ("demo-model-a", "demo-model-b")
            ],
        )
        self.disabled: set[str] = set()

    def list_models(self) -> ModelList:
        items = [
            item.model_copy(deep=True) for item in self.models.items if item.id not in self.disabled
        ]
        if not items or self.models.default_model_id not in {item.id for item in items}:
            raise PlatformError(422, "MODEL_UNAVAILABLE", "默认演示模型不可用")
        return ModelList(default_model_id=self.models.default_model_id, items=items)

    def resolve(self, model_id: str, capability: str, now: str) -> ModelMetadata:
        model = next((item for item in self.list_models().items if item.id == model_id), None)
        if model is None or capability not in model.capabilities:
            raise PlatformError(422, "MODEL_UNAVAILABLE", "模型不可用或不支持此任务")
        return ModelMetadata(
            model_id=model.id,
            provider=model.provider,
            model="api-01-synthetic-stub",
            prompt_version="api-01-fake-v1",
            gateway_config_version="api-01-fake-v1",
            generated_at=now,
        )
