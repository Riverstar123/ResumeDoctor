"""M5 网关的冻结输出结构：四类 task_name 对应的 JSON Schema。

消费者通过 `ModelGateway.generate_structured` 传入 `output_schema`。AI-01 只实现
冻结的四种结构：调用方必须传入与 `task_output_schema(task_name)` 一致的 Schema，
否则网关显式失败，不按 task_name 静默套用另一种结构——否则消费者会在 fake 下
通过、换上遵守同一端口的真实适配器后才暴露输出契约错误。比对只在 Schema 节点
忽略 `title`/`description` 文档注释，字段名与约束一律保留；`task_output_schema`
返回深拷贝，调用方调整自己的 Schema 不会改动冻结基准。

`profile_chat` 的输出不是单个契约 DTO，而是「助手消息 + 档案草稿」的包装结构，
这里用 `ChatOutput` 冻结，供调用方直接取用同一份 Schema。按任意 JSON Schema 校验
由 AI-02 的真实适配器交付。
"""

import copy
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
    """返回某任务冻结的输出 Schema；调用方应原样传给网关。

    返回深拷贝：调用方可以按自己的需要调整这份 Schema（例如加自己的字段），但不会
    改动全局冻结基准，也不会影响其他调用方或后续校验。
    """
    return copy.deepcopy(TASK_OUTPUT_SCHEMAS[task_name])


def schema_matches_task(task_name: str, output_schema: Mapping[str, Any]) -> bool:
    """调用方传入的 Schema 是否等同于该任务冻结的结构。

    比较时只在真正的 Schema 节点忽略 title/description——它们只影响文档展示，不改变
    数据形状，因此手工抄写或换个模型名生成、但字段与约束一致的 Schema 仍被接受；
    字段不同的（例如把 JobContent 的 Schema 传给 profile_extract）不匹配。
    `properties`、`$defs` 等映射的键是字段名而非关键字，全部保留：把
    `properties.title` 的约束改成 integer，或改 `$defs.Gap.properties.description`，
    都算不同结构，不得放行。
    """
    expected = TASK_OUTPUT_SCHEMAS.get(task_name)
    if expected is None:
        return False
    if not isinstance(output_schema, Mapping):
        return False
    return _data_shape(output_schema) == _data_shape(expected)


# 值是「名称 → Schema」映射的关键字：键是字段名，必须原样保留。
_NAME_MAP_KEYWORDS = frozenset(
    {"properties", "patternProperties", "dependentSchemas", "$defs", "definitions"}
)
# 值是单个子 Schema 的关键字。
_SINGLE_SCHEMA_KEYWORDS = frozenset(
    {
        "items",
        "additionalProperties",
        "additionalItems",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
# 值是子 Schema 列表的关键字。
_SCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
# 纯文档注释：只在 Schema 节点上忽略，且必须是非空字符串（Schema 关键字语义）。
_ANNOTATION_KEYWORDS = frozenset({"title", "description"})


def _data_shape(node: Any) -> Any:
    """把 Schema 归一为可比对的数据形状：只丢弃 Schema 节点的文档注释。

    其余键一律按原样保留，包括 enum/const/required/type 等约束，以及
    `properties`、`$defs` 里名为 title/description 的业务字段。
    """
    if not isinstance(node, Mapping):
        return node
    shape: dict[str, Any] = {}
    for key, value in node.items():
        if key in _ANNOTATION_KEYWORDS and isinstance(value, str):
            continue
        if key in _NAME_MAP_KEYWORDS and isinstance(value, Mapping):
            shape[key] = {name: _data_shape(sub) for name, sub in value.items()}
        elif key in _SINGLE_SCHEMA_KEYWORDS:
            shape[key] = _data_shape(value)
        elif key in _SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            shape[key] = [_data_shape(item) for item in value]
        else:
            shape[key] = value
    return shape
