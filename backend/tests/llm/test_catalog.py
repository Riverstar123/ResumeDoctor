"""假模型目录：公开元信息、能力筛选与失败边界。

验证范围 T19/T21 的 fake 场景：下拉列表来自受控目录，未知/停用/能力不匹配的
model_id 明确失败，公开 DTO 不含密钥或端点。
"""

import pytest

from app.llm import TASK_NAMES, FakeModelDirectory, GatewayError, ModelEntry

NOW = "2026-10-14T00:00:00Z"


def test_two_fake_entries_are_clearly_labelled_and_cover_four_tasks():
    directory = FakeModelDirectory()
    listing = directory.list_models()
    assert [item.id for item in listing.items] == ["demo-model-a", "demo-model-b"]
    assert listing.default_model_id == "demo-model-a"
    for item in listing.items:
        assert item.provider == "fake"
        assert item.display_name.startswith("演示数据 /")
        assert tuple(item.capabilities) == TASK_NAMES


def test_public_model_dto_exposes_no_secret_or_endpoint_fields():
    directory = FakeModelDirectory()
    payload = directory.list_models().model_dump(mode="json")
    serialized = repr(payload).lower()
    for forbidden in ("key", "secret", "token", "base_url", "endpoint", "password"):
        assert forbidden not in serialized


def test_resolve_returns_fake_metadata_with_per_task_prompt_version():
    directory = FakeModelDirectory()
    for task in TASK_NAMES:
        metadata = directory.resolve("demo-model-b", task, NOW)
        assert metadata.model_id == "demo-model-b"
        assert metadata.provider == "fake"
        assert metadata.model == "synthetic-fake-v1"
        assert metadata.gateway_config_version == "fake-gateway-v1"
        assert metadata.generated_at == NOW
    assert directory.resolve("demo-model-a", "diagnosis_report", NOW).prompt_version == "report-v1"
    assert directory.resolve("demo-model-a", "profile_chat", NOW).prompt_version == "chat-v1"


def test_unknown_model_id_fails_clearly():
    with pytest.raises(GatewayError) as error:
        FakeModelDirectory().resolve("does-not-exist", "profile_extract", NOW)
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_disabled_model_is_not_listed_and_cannot_be_resolved():
    directory = FakeModelDirectory()
    directory.disable("demo-model-b")
    assert [item.id for item in directory.list_models().items] == ["demo-model-a"]
    with pytest.raises(GatewayError) as error:
        directory.resolve("demo-model-b", "job_extract", NOW)
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_disabling_the_default_makes_the_list_unavailable():
    directory = FakeModelDirectory()
    directory.disable("demo-model-a")
    with pytest.raises(GatewayError) as error:
        directory.list_models()
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_capability_mismatch_fails_clearly():
    entry = ModelEntry(
        id="limited",
        display_name="演示数据 / limited",
        provider="fake",
        model="synthetic-fake-v1",
        capabilities=("profile_extract",),
    )
    directory = FakeModelDirectory(entries=(entry,), default_model_id="limited")
    assert directory.resolve("limited", "profile_extract", NOW).model_id == "limited"
    with pytest.raises(GatewayError) as error:
        directory.resolve("limited", "diagnosis_report", NOW)
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_unknown_capability_fails_clearly():
    with pytest.raises(GatewayError) as error:
        FakeModelDirectory().resolve("demo-model-a", "not_a_task", NOW)
    assert error.value.code == "MODEL_UNAVAILABLE"
