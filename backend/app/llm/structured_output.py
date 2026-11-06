"""Provider wire formats; the original schema is still validated locally.

DeepSeek strict tool calls support a subset of JSON Schema. Inline local refs,
require every object property and omit unsupported length annotations only on
the wire. Never change business field names or weaken the local validator.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from .errors import GatewayError

RESULT_TOOL = "submit_structured_result"
_KEYWORDS = {
    "type",
    "enum",
    "anyOf",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "pattern",
}
_FORMATS = {"email", "hostname", "ipv4", "ipv6", "uuid"}


def compact_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Remove documentation only at schema nodes, including within named fields."""
    result = deepcopy(dict(schema))
    for name in ("title", "description", "default"):
        result.pop(name, None)
    for name in ("properties", "$defs", "definitions", "patternProperties"):
        if name in result:
            result[name] = {key: compact_schema(value) for key, value in result[name].items()}
    for name in ("items", "additionalProperties", "not"):
        if isinstance(result.get(name), Mapping):
            result[name] = compact_schema(result[name])
    for name in ("anyOf", "oneOf", "allOf", "prefixItems"):
        if isinstance(result.get(name), list):
            result[name] = [compact_schema(value) for value in result[name]]
    return result


def deepseek_strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    root = deepcopy(dict(schema))

    def convert(node, seen=()):
        node = dict(node)
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
                raise GatewayError(
                    "MODEL_UNAVAILABLE", "严格结构输出只支持无递归的本地 Schema 引用"
                )
            target = root
            try:
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                raise GatewayError("MODEL_UNAVAILABLE", "严格结构输出的 Schema 引用无效") from None
            return convert(
                {**target, **{k: v for k, v in node.items() if k != "$ref"}}, (*seen, ref)
            )
        result = {key: deepcopy(value) for key, value in node.items() if key in _KEYWORDS}
        if "const" in node:
            result["enum"] = [node["const"]]
        if node.get("format") in _FORMATS:
            result["format"] = node["format"]
        if "anyOf" in result:
            result["anyOf"] = [convert(value, seen) for value in result["anyOf"]]
        if result.get("type") == "object" or "properties" in result:
            if node.get("additionalProperties") not in (None, False):
                raise GatewayError("MODEL_UNAVAILABLE", "严格结构输出不支持开放的字典字段")
            result["type"] = "object"
            result["properties"] = {
                key: convert(value, seen) for key, value in node.get("properties", {}).items()
            }
            result["required"] = list(result["properties"])
            result["additionalProperties"] = False
        if "items" in result:
            result["items"] = convert(result["items"], seen)
        if not result or any(key in node for key in ("oneOf", "allOf", "not")):
            raise GatewayError("MODEL_UNAVAILABLE", "当前 Schema 不支持供应商严格结构输出")
        return result

    return convert(root)


def strict_endpoint(base_url: str) -> str:
    """Opt in only on the configured official origin; never redirect credentials."""
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError:
        raise GatewayError("MODEL_UNAVAILABLE", "DeepSeek 严格结构输出端点无效") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.deepseek.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/")
        not in (
            "",
            "/v1",
            "/beta",
            "/chat/completions",
            "/v1/chat/completions",
            "/beta/chat/completions",
        )
    ):
        raise GatewayError("MODEL_UNAVAILABLE", "DeepSeek 严格结构输出需要官方 HTTPS 端点")
    return "https://api.deepseek.com/beta/chat/completions"


def output_parameters(
    schema: Mapping[str, Any], strict: bool, context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if not strict:
        return {"response_format": {"type": "json_object"}}
    parameters = deepseek_strict_schema(schema)
    suggestions = parameters.get("properties", {}).get("suggestions", {})
    properties = suggestions.get("items", {}).get("properties", {})
    if context and context.get("suggestion_policy") == "supported_facts_only":
        if "requires_user_input" in properties:
            properties["requires_user_input"] = {"type": "boolean", "enum": [False]}
    if context and context.get("review_prompt_version") == "report-grounding-v7":
        if "evidence_checks" in parameters.get("properties", {}):
            parameters["properties"]["evidence_checks"] = {"type": "null"}
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": RESULT_TOOL,
                    "description": "Return the requested structured result as data. No external action.",
                    "strict": True,
                    "parameters": parameters,
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": RESULT_TOOL}},
    }
