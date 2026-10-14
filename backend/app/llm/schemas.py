"""M5 网关的冻结输出结构：四类 task_name 对应的 JSON Schema。

消费者通过 `ModelGateway.generate_structured` 传入 `output_schema`。AI-01 只实现
冻结的四种结构：调用方必须传入与 `task_output_schema(task_name)` 一致的 Schema，
否则网关显式失败，不按 task_name 静默套用另一种结构——否则消费者会在 fake 下
通过、换上遵守同一端口的真实适配器后才暴露输出契约错误。

`profile_chat` 的输出不是单个契约 DTO，而是「助手消息 + 档案草稿」的包装结构，
这里用 `ChatOutput` 冻结，供调用方直接取用同一份 Schema。按任意 JSON Schema 校验
由 AI-02 的真实适配器交付。
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.contracts import JobContent, ProfileContent, ReportContent


class ChatOutput(BaseModel):
    """profile_chat 的输出包装：助手消息 + 档案草稿。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    assistant_message: str
    profile_content: ProfileContent


# task_name → 输出结构的唯一来源；网关按此校验 result，也按此比对调用方 Schema。
TASK_OUTPUT_DTOS: dict[str, type[BaseModel]] = {
    "profile_extract": ProfileContent,
    "profile_chat": ChatOutput,
    "job_extract": JobContent,
    "diagnosis_report": ReportContent,
}

TASK_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    name: model.model_json_schema() for name, model in TASK_OUTPUT_DTOS.items()
}


def task_output_schema(task_name: str) -> dict[str, Any]:
    """返回某任务冻结的输出 Schema；调用方应原样传给网关。"""
    return TASK_OUTPUT_SCHEMAS[task_name]


def schema_matches_task(task_name: str, output_schema: Mapping[str, Any]) -> bool:
    """调用方传入的 Schema 是否等同于该任务冻结的结构。

    比较时忽略 title/description：它们只影响文档展示，不改变数据形状，因此手工
    抄写或换个模型名生成、但字段一致的 Schema 仍被接受；字段不同的（例如把
    JobContent 的 Schema 传给 profile_extract）不匹配。
    """
    expected = TASK_OUTPUT_SCHEMAS.get(task_name)
    if expected is None:
        return False
    if not isinstance(output_schema, Mapping):
        return False
    return _data_shape(output_schema) == _data_shape(expected)


def _data_shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _data_shape(item)
            for key, item in value.items()
            if key not in {"title", "description"}
        }
    if isinstance(value, list):
        return [_data_shape(item) for item in value]
    return value
