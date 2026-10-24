"""AI-02 真实适配器：协议、双模型映射、错误/重试、配置校验与 fake 回退。

所有 HTTP 都由 `httpx.MockTransport` 桩完成，不读取真实密钥，也不消耗任何
供应商额度。覆盖 T11（超时/非法 JSON/429）、T19（多模型映射）与 T21（无效/
不支持任务的 model_id），以及 Issue #23 的缺配置明确失败和不泄露端点/密钥。
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.contracts.ports import TaskContext
from app.llm import (
    DEFAULT_CONFIG_PATH,
    FakeModelDirectory,
    FakeModelGateway,
    GatewayError,
    OpenAICompatibleGateway,
    build_llm,
    load_model_config,
    task_output_schema,
)
from app.llm.synthetic import synthetic_job_payload, synthetic_profile_payload
from app.settings import Settings

CUSTOM_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
CONTEXT = TaskContext(model_id="real-default")


def real_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "llm_mode": "real",
        "llm_provider": "openai_compatible",
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "test-secret-key",
        "llm_model": "gpt-default",
        "llm_model_a": "model-a",
        "llm_model_b": "model-b",
    }
    values.update(overrides)
    return Settings(**values)


def ok(payload) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def raw(content) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class Stub:
    """按顺序返回预设响应；只剩一个时重复使用，记录所有请求。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if asyncio.iscoroutinefunction(item):
            return await item(request)
        return item


def build(responses, **overrides):
    settings = real_settings(**overrides)
    stub = Stub(responses)
    components = build_llm(settings, transport=httpx.MockTransport(stub))
    return components, stub


def generate(gateway, task="profile_extract", payload=None, schema=None, context=CONTEXT):
    if payload is None:
        payload = {"ok": True}
    if schema is None:
        schema = CUSTOM_SCHEMA
    return asyncio.run(
        gateway.generate_structured(
            task,
            {"prompt": "系统提示", "source_text": "合成原文"},
            schema,
            5.0,
            context=context,
        )
    )


def test_chat_completions_request_shape_and_metadata():
    components, stub = build([ok({"ok": True})])
    result = generate(components.gateway)

    request = stub.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-secret-key"
    body = json.loads(request.content)
    assert body["model"] == "gpt-default"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "系统提示"}
    assert '"source_text"' in body["messages"][1]["content"]
    assert '"ok"' in body["messages"][1]["content"]
    assert result.data == {"ok": True}
    assert result.model_metadata.model_id == "real-default"
    assert result.model_metadata.provider == "openai_compatible"
    assert result.model_metadata.model == "gpt-default"
    assert result.model_metadata.prompt_version == "profile-v1"
    assert result.model_metadata.gateway_config_version == "models-v1"


def test_report_request_uses_3000_output_tokens():
    components, stub = build([ok({"ok": True})])
    asyncio.run(
        components.gateway.generate_structured(
            "diagnosis_report",
            {"prompt": "报告提示"},
            CUSTOM_SCHEMA,
            5.0,
            context=CONTEXT,
        )
    )
    body = json.loads(stub.requests[0].content)
    assert body["max_tokens"] == 3000


def test_two_models_map_to_two_actual_model_names():
    components, stub = build([ok(synthetic_profile_payload()), ok(synthetic_job_payload())])
    profile = asyncio.run(
        components.gateway.generate_structured(
            "profile_extract",
            {"prompt": "提取"},
            task_output_schema("profile_extract"),
            5.0,
            context=TaskContext(model_id="real-model-a"),
        )
    )
    job = asyncio.run(
        components.gateway.generate_structured(
            "job_extract",
            {"prompt": "提取"},
            task_output_schema("job_extract"),
            5.0,
            context=TaskContext(model_id="real-model-b"),
        )
    )
    first, second = (json.loads(request.content) for request in stub.requests)
    assert first["model"] == "model-a"
    assert second["model"] == "model-b"
    assert profile.model_metadata.model == "model-a"
    assert job.model_metadata.model == "model-b"
    assert [call.model_id for call in components.gateway.calls] == [
        "real-model-a",
        "real-model-b",
    ]


def test_public_list_contains_no_key_or_endpoint():
    components, _ = build([ok({"ok": True})])
    payload = components.directory.list_models().model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("test-secret-key", "llm.example", "base_url", "api_key", "endpoint"):
        assert forbidden not in serialized
    assert [item["id"] for item in payload["items"]] == [
        "real-default",
        "real-model-a",
        "real-model-b",
    ]
    assert payload["default_model_id"] == "real-default"


def test_connection_repr_hides_api_key():
    components, _ = build([ok({"ok": True})])
    connection = components.directory.connection("real-default")
    assert "test-secret-key" not in repr(connection)
    assert connection.model == "gpt-default"


def test_429_retries_once_then_succeeds():
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    settings = real_settings()
    stub = Stub([httpx.Response(429), ok({"ok": True})])
    gateway = OpenAICompatibleGateway(
        build_llm(settings, transport=httpx.MockTransport(stub)).directory,
        transport=httpx.MockTransport(stub),
        sleep=sleep,
        clock=lambda: "2026-10-23T00:00:00Z",
    )
    result = generate(gateway)
    assert result.data == {"ok": True}
    assert len(stub.requests) == 2
    assert sleeps == [0.1]
    assert gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "ok"


def test_5xx_twice_fails_as_provider_unavailable_after_one_retry():
    settings = real_settings()
    stub = Stub([httpx.Response(503), httpx.Response(503)])
    gateway = OpenAICompatibleGateway(
        build_llm(settings, transport=httpx.MockTransport(stub)).directory,
        transport=httpx.MockTransport(stub),
        sleep=lambda _: asyncio.sleep(0),
    )
    with pytest.raises(GatewayError) as error:
        generate(gateway)
    assert error.value.code == "PROVIDER_UNAVAILABLE"
    assert len(stub.requests) == 2
    assert gateway.calls[0].attempts == 2
    assert gateway.calls[0].outcome == "PROVIDER_UNAVAILABLE"


def test_auth_failure_is_not_retried_and_does_not_leak_key():
    components, stub = build([httpx.Response(401)])
    with pytest.raises(GatewayError) as error:
        generate(components.gateway)
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert len(stub.requests) == 1
    assert "test-secret-key" not in str(error.value)


def test_invalid_json_gets_one_repair_then_succeeds():
    components, stub = build([raw("{不是 JSON"), ok({"ok": True})])
    result = generate(components.gateway)
    assert result.data == {"ok": True}
    assert len(stub.requests) == 2
    second = json.loads(stub.requests[1].content)
    roles = [message["role"] for message in second["messages"]]
    assert roles[-2:] == ["assistant", "user"]
    assert "上一次输出不是合法 JSON" in second["messages"][-1]["content"]


def test_invalid_json_twice_fails_after_shared_budget():
    components, stub = build([raw("{不是 JSON"), raw("也不是 JSON")])
    with pytest.raises(GatewayError) as error:
        generate(components.gateway)
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert len(stub.requests) == 2
    assert components.gateway.calls[0].attempts == 2
    assert components.gateway.calls[0].outcome == "MODEL_OUTPUT_INVALID"


def test_schema_mismatch_is_repaired_once():
    components, stub = build([ok({"ok": "yes"}), ok({"ok": True})])
    result = generate(components.gateway)
    assert result.data == {"ok": True}
    assert len(stub.requests) == 2


def test_shared_retry_budget_across_provider_and_format_failures():
    components, stub = build([httpx.Response(500), raw("{不是 JSON")])
    with pytest.raises(GatewayError) as error:
        generate(components.gateway)
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert len(stub.requests) == 2


def test_timeout_is_not_retried():
    async def slow(_request):
        await asyncio.sleep(1)
        return ok({"ok": True})

    components, stub = build([slow])
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            components.gateway.generate_structured(
                "profile_extract", {"prompt": "x"}, CUSTOM_SCHEMA, 0.02, context=CONTEXT
            )
        )
    assert error.value.code == "MODEL_TIMEOUT"
    assert len(stub.requests) == 1
    assert components.gateway.calls[0].attempts == 1


def test_input_over_limit_fails_before_any_request():
    components, stub = build([ok({"ok": True})])
    with pytest.raises(GatewayError) as error:
        asyncio.run(
            components.gateway.generate_structured(
                "diagnosis_report", {"prompt": "x" * 20_001}, CUSTOM_SCHEMA, 5.0, context=CONTEXT
            )
        )
    assert error.value.code == "INPUT_TOO_LONG"
    assert stub.requests == []


def test_malformed_envelope_is_an_invalid_output():
    components, stub = build([httpx.Response(200, json={})])
    with pytest.raises(GatewayError) as error:
        generate(components.gateway)
    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert len(stub.requests) == 2


def test_unknown_or_unsupported_model_fails_before_request():
    components, stub = build([ok({"ok": True})])
    with pytest.raises(GatewayError) as error:
        generate(components.gateway, context=TaskContext(model_id="missing-model"))
    assert error.value.code == "MODEL_UNAVAILABLE"
    with pytest.raises(GatewayError) as error:
        generate(components.gateway, task="not_a_task")
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert stub.requests == []


def test_capability_mismatch_is_rejected():
    from app.llm import configured_directory

    config = load_model_config()
    entry = config.models[1].model_copy(update={"capabilities": ["profile_extract"]})
    config = config.model_copy(update={"models": [config.models[0], entry, config.models[2]]})
    narrow = configured_directory(config, real_settings())
    with pytest.raises(GatewayError) as error:
        narrow.resolve("real-model-a", "diagnosis_report", "2026-10-23T00:00:00Z")
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_disabled_entry_is_not_listed_and_cannot_be_resolved(tmp_path):
    path = write_config(
        tmp_path,
        """
version: test-v1
default_model_id: default
models:
  - id: default
    display_name: 默认
    provider: openai_compatible
    capabilities: [profile_extract]
    model_env: LLM_MODEL
  - id: disabled
    display_name: 停用
    provider: openai_compatible
    capabilities: [profile_extract]
    enabled: false
    model_env: LLM_MODEL_A
""",
    )
    settings = real_settings()
    components = build_llm(settings, config_path=path, transport=httpx.MockTransport(Stub([])))
    assert [item.id for item in components.directory.list_models().items] == ["default"]
    with pytest.raises(GatewayError) as error:
        components.directory.resolve("disabled", "profile_extract", "2026-10-23T00:00:00Z")
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_missing_default_configuration_fails_at_startup_without_secret():
    for overrides, expected in (
        ({"llm_base_url": ""}, "LLM_BASE_URL"),
        ({"llm_api_key": ""}, "LLM_API_KEY"),
        ({"llm_model": ""}, "LLM_MODEL"),
    ):
        with pytest.raises(GatewayError) as error:
            build_llm(real_settings(**overrides))
        assert error.value.code == "MODEL_UNAVAILABLE"
        assert expected in str(error.value)
        assert "test-secret-key" not in str(error.value)


def test_missing_llm_model_is_rejected_in_real_mode():
    # Omitted LLM_MODEL must not fall back to the old demo placeholder.
    settings = Settings(
        _env_file=None,
        llm_mode="real",
        llm_provider="openai_compatible",
        llm_base_url="https://llm.example/v1",
        llm_api_key="test-secret-key",
    )
    with pytest.raises(GatewayError) as error:
        build_llm(settings)
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert "LLM_MODEL" in str(error.value)
    assert "test-secret-key" not in str(error.value)


def test_demo_placeholder_model_is_rejected_in_real_mode():
    with pytest.raises(GatewayError) as error:
        build_llm(real_settings(llm_model="fake-default"))
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert "LLM_MODEL" in str(error.value)
    assert "fake-default" in str(error.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://llm.example:abc/v1",
        "https://llm.example:65536/v1",
        "https://llm.example/v1\x00",
    ],
)
def test_invalid_base_url_fails_at_startup_without_echoing_it(base_url):
    with pytest.raises(GatewayError) as error:
        build_llm(real_settings(llm_base_url=base_url))
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert "LLM_BASE_URL" in str(error.value)
    for leaked in ("abc", "65536", "llm.example"):
        assert leaked not in str(error.value)


def test_explicit_valid_port_is_accepted():
    components, stub = build(
        [ok({"ok": True})],
        llm_base_url="https://llm.example:8443/v1",
    )
    generate(components.gateway)
    assert str(stub.requests[0].url) == "https://llm.example:8443/v1/chat/completions"


def test_missing_optional_entry_is_omitted_but_default_still_works():
    components = build_llm(
        real_settings(llm_model_a=""), transport=httpx.MockTransport(Stub([ok({"ok": True})]))
    )
    assert [item.id for item in components.directory.list_models().items] == [
        "real-default",
        "real-model-b",
    ]
    with pytest.raises(GatewayError) as error:
        components.directory.resolve("real-model-a", "profile_extract", "2026-10-23T00:00:00Z")
    assert "LLM_MODEL_A" in str(error.value)


def test_fake_mode_uses_fake_components_and_no_config_file():
    components = build_llm(Settings(_env_file=None))
    assert isinstance(components.directory, FakeModelDirectory)
    assert isinstance(components.gateway, FakeModelGateway)
    assert components.gateway.calls == []


def test_unsupported_provider_fails_clearly():
    with pytest.raises(GatewayError) as error:
        build_llm(real_settings(llm_provider="anthropic"))
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert "openai_compatible" in str(error.value)


def test_invalid_base_url_with_credentials_is_rejected_without_echoing_it():
    with pytest.raises(GatewayError) as error:
        build_llm(real_settings(llm_base_url="https://user:password@llm.example/v1"))
    assert "LLM_BASE_URL" in str(error.value)
    assert "password" not in str(error.value)


def test_base_url_ending_in_endpoint_is_not_duplicated():
    components, stub = build(
        [ok({"ok": True})],
        llm_base_url="https://llm.example/v1/chat/completions",
    )
    generate(components.gateway)
    assert str(stub.requests[0].url) == "https://llm.example/v1/chat/completions"


def test_invalid_catalog_does_not_echo_planted_value(tmp_path):
    path = write_config(
        tmp_path,
        """
version: test-v1
default_model_id: default
unknown_secret: sk-should-not-print
models:
  - id: default
    display_name: 默认
    provider: openai_compatible
    capabilities: [profile_extract]
    model_env: LLM_MODEL
""",
    )
    with pytest.raises(GatewayError) as error:
        build_llm(real_settings(), config_path=path)
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert "sk-should-not-print" not in str(error.value)


def test_duplicate_ids_and_unknown_capability_are_rejected(tmp_path):
    duplicate = write_config(
        tmp_path,
        """
version: test-v1
default_model_id: default
models:
  - id: default
    display_name: 默认
    provider: openai_compatible
    capabilities: [profile_extract]
    model_env: LLM_MODEL
  - id: default
    display_name: 重复
    provider: openai_compatible
    capabilities: [profile_extract]
    model_env: LLM_MODEL_A
""",
    )
    with pytest.raises(GatewayError) as error:
        load_model_config(duplicate)
    assert "重复" in str(error.value)

    unknown = write_config(
        tmp_path,
        """
version: test-v1
default_model_id: default
models:
  - id: default
    display_name: 默认
    provider: openai_compatible
    capabilities: [not_a_task]
    model_env: LLM_MODEL
""",
        name="unknown.yaml",
    )
    with pytest.raises(GatewayError) as error:
        load_model_config(unknown)
    assert "not_a_task" in str(error.value)


def test_committed_catalog_has_no_secret_or_endpoint():
    config = load_model_config()
    assert config.default_model_id == "real-default"
    assert [entry.id for entry in config.models] == [
        "real-default",
        "real-model-a",
        "real-model-b",
    ]
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "https://" not in text
    assert "http://" not in text


def write_config(directory: Path, text: str, *, name: str = "models.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path
