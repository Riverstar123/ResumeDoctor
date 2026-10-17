import asyncio
import json

import pytest

from app.contracts import Profile, ProfileContent
from app.contracts.ports import TaskContext
from app.intake import HISTORY_LIMIT, GatewayIntake, IntakeError, synthetic_profile_content
from app.intake.privacy import filter_fake_context
from app.llm import FakeModelDirectory, FakeModelGateway
from tests.intake.test_gateway_intake import StubGateway, chat_payload, user_message

CONTEXT = TaskContext(model_id="demo-model-a")
EMPTY = ProfileContent(overview="", as_of_month="2026-09", facts=[], evidence=[])


def test_keep_previously_verified_profile_when_source_is_outside_history():
    previous = synthetic_profile_content()
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": previous.model_dump(mode="json"),
            }
        }
    )
    result = asyncio.run(
        GatewayIntake(gateway, source_id="current-message").advance_conversation(
            "暂时没有补充。", previous, [], context=CONTEXT
        )
    )
    assert result.profile_content == previous


def test_history_source_ids_are_visible_to_gateway():
    message = user_message("我做过一个 Python 项目。", 1)
    gateway = StubGateway({"profile_chat": chat_payload(message.content, message_id=message.id)})
    asyncio.run(
        GatewayIntake(gateway, source_id="current-message").advance_conversation(
            "继续。", EMPTY, [message], context=CONTEXT
        )
    )
    assert message.id in json.dumps(gateway.calls[0]["prompt_context"], ensure_ascii=False)


def test_history_text_is_not_duplicated_in_gateway_input_budget():
    gateway = FakeModelGateway(FakeModelDirectory())
    history = [user_message("合成背景" * 450, index) for index in range(HISTORY_LIMIT)]
    result = asyncio.run(
        GatewayIntake(gateway).advance_conversation(
            "没有新增事实。",
            synthetic_profile_content(),
            history,
            context=CONTEXT,
        )
    )
    assert result.profile_content == synthetic_profile_content()
    assert gateway.calls[0].outcome == "ok"
    assert gateway.calls[0].input_chars < 30000


def test_two_conversation_rounds_keep_old_evidence_and_bind_each_new_message():
    first_message = user_message("我做过数据清洗。", 1)
    first_gateway = StubGateway(
        {
            "profile_chat": chat_payload(
                first_message.content,
                message_id=first_message.id,
            )
        }
    )
    first = asyncio.run(
        GatewayIntake(first_gateway, source_id=first_message.id).advance_conversation(
            first_message.content,
            EMPTY,
            [],
            context=CONTEXT,
        )
    )
    second_message = user_message("我了解 SQL。", 2)
    combined = first.profile_content.model_dump(mode="json")
    new = chat_payload(second_message.content, message_id=second_message.id)["profile_content"]
    new["facts"][0].update(
        id="f2", kind="skill", label="SQL", application="claimed", evidence_ids=["e2"]
    )
    new["evidence"][0]["id"] = "e2"
    combined["facts"].extend(new["facts"])
    combined["evidence"].extend(new["evidence"])
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": combined,
            }
        }
    )
    result = asyncio.run(
        GatewayIntake(gateway, source_id=second_message.id).advance_conversation(
            second_message.content,
            first.profile_content,
            [first_message],
            context=CONTEXT,
        )
    )
    assert result.profile_content.evidence[0] == first.profile_content.evidence[0]
    assert [item.source_id for item in result.profile_content.evidence] == [
        first_message.id,
        second_message.id,
    ]
    assert result.profile_content.facts[1].evidence_ids == ["e2"]


def test_contacts_do_not_reach_gateway():
    text = "我做过数据清洗。邮箱 candidate@example.invalid，电话 13800000000。"
    gateway = StubGateway({"profile_chat": chat_payload("我做过数据清洗。")})
    asyncio.run(GatewayIntake(gateway).advance_conversation(text, EMPTY, [], context=CONTEXT))
    sent = json.dumps(gateway.calls[0]["prompt_context"], ensure_ascii=False)
    assert "candidate@example.invalid" not in sent
    assert "13800000000" not in sent


def test_old_message_remains_verifiable_after_history_window_moves():
    previous = synthetic_profile_content()
    oldest = user_message(previous.evidence[0].quote, 1)
    previous.evidence[0].source_id = oldest.id
    previous.evidence[0].source_type = "message"
    history = [oldest] + [user_message(f"补充 {i}", i + 2) for i in range(HISTORY_LIMIT)]
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": previous.model_dump(mode="json"),
            }
        }
    )
    result = asyncio.run(
        GatewayIntake(gateway, source_id="current-message").advance_conversation(
            "没有补充。",
            previous,
            history,
            context=CONTEXT,
        )
    )
    assert result.profile_content == previous
    sent = gateway.calls[0]["prompt_context"]
    assert oldest.id not in {message["source_id"] for message in sent["history_user_messages"]}
    assert len(sent["history_user_messages"]) == HISTORY_LIMIT


@pytest.mark.parametrize("field", ["facts", "evidence"])
def test_model_cannot_drop_previous_snapshot_items(field):
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload[field] = payload[field][1:]
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": payload,
            }
        }
    )
    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(gateway).advance_conversation(
                "没有补充。",
                previous,
                [],
                context=CONTEXT,
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_reusing_an_old_evidence_id_does_not_authorize_changed_quote():
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload["evidence"][0]["quote"] = "完全伪造的课程成果。"
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": payload,
            }
        }
    )
    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(gateway).advance_conversation(
                "没有补充。",
                previous,
                [],
                context=CONTEXT,
            )
        )
    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_new_evidence_cannot_claim_an_unavailable_old_source():
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload["evidence"].append({**payload["evidence"][0], "id": "new-evidence"})
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": payload,
            }
        }
    )
    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(gateway, source_id="current-message").advance_conversation(
                "没有补充。",
                previous,
                [],
                context=CONTEXT,
            )
        )
    assert error.value.code == "UNKNOWN_SOURCE"


def test_build_profile_can_preserve_the_verified_previous_snapshot():
    previous = Profile(
        id="00000000-0000-4000-8000-000000000099",
        version=1,
        confirmed=True,
        content=synthetic_profile_content(),
        created_at="2026-10-15T00:00:00Z",
    )
    gateway = StubGateway({"profile_extract": previous.content.model_dump(mode="json")})
    result = asyncio.run(
        GatewayIntake(gateway, source_id="new-document").build_profile(
            "没有新增事实。",
            "document",
            previous,
            context=CONTEXT,
        )
    )
    assert result == previous.content


def test_assistant_messages_cannot_become_sources_or_fill_the_history_window():
    user = user_message("我做过一个 Python 项目。", 1)
    assistant = user_message("模型猜测的成果。", 2).model_copy(update={"role": "assistant"})
    gateway = StubGateway({"profile_chat": chat_payload(user.content, message_id=user.id)})
    asyncio.run(
        GatewayIntake(gateway).advance_conversation(
            "继续。",
            EMPTY,
            [user] + [assistant] * HISTORY_LIMIT,
            context=CONTEXT,
        )
    )
    sent = gateway.calls[0]["prompt_context"]
    assert sent["history_user_messages"] == [{"source_id": user.id, "content": user.content}]


def test_source_type_must_agree_with_current_input():
    payload = chat_payload("我做过数据清洗。")
    payload["profile_content"]["evidence"][0]["source_type"] = "document"
    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(StubGateway({"profile_chat": payload})).advance_conversation(
                "我做过数据清洗。",
                EMPTY,
                [],
                context=CONTEXT,
            )
        )
    assert error.value.code == "INVALID_SOURCE_TYPE"


def test_filtered_old_evidence_is_restored_only_from_verified_snapshot():
    previous = synthetic_profile_content()
    previous.overview = "合成档案，邮箱 candidate@example.invalid"
    previous.evidence[0].quote += " 联系电话：13800000000。"
    original = previous.model_dump(mode="json")
    gateway = StubGateway(
        {
            "profile_chat": {
                "assistant_message": "请继续。",
                "profile_content": filter_fake_context(original),
            }
        }
    )
    result = asyncio.run(
        GatewayIntake(gateway).advance_conversation(
            "没有补充。",
            previous,
            [],
            context=CONTEXT,
        )
    )
    assert result.profile_content.evidence == previous.evidence
    assert previous.model_dump(mode="json") == original
    sent = json.dumps(gateway.calls[0]["prompt_context"], ensure_ascii=False)
    assert "candidate@example.invalid" not in sent and "13800000000" not in sent


def test_unconfigured_non_fake_gateway_is_rejected_before_call():
    gateway = StubGateway()
    gateway.is_fake = False
    with pytest.raises(IntakeError) as error:
        asyncio.run(GatewayIntake(gateway).extract_job("合成 JD。", "", context=CONTEXT))
    assert error.value.code == "PRIVACY_FILTER_REQUIRED"
    assert gateway.calls == []


def test_explicit_filter_is_used_once_for_non_fake_gateway():
    gateway = StubGateway({"profile_chat": chat_payload("我做过数据清洗。")})
    gateway.is_fake = False  # Still a local stub: this test sends no network traffic.
    calls = []

    def policy(value):
        calls.append(value)
        return filter_fake_context(value)

    asyncio.run(
        GatewayIntake(gateway, privacy_filter=policy).advance_conversation(
            "我做过数据清洗。邮箱 candidate@example.invalid。",
            EMPTY,
            [],
            context=CONTEXT,
        )
    )
    assert len(calls) == 1
    assert "candidate@example.invalid" not in json.dumps(gateway.calls[0]["prompt_context"])


def test_fake_filter_covers_nested_context_without_changing_dates_or_input():
    value = {
        "nested": [
            "邮箱 candidate@example.invalid",
            "手机 +86 138-0000-0000",
            "电话：010-12345678。",
            "联系地址：合成街道 123 号。",
            "phone +1 (202) 555-0100",
            "2026-09",
        ]
    }
    original = json.dumps(value, ensure_ascii=False)
    filtered = json.dumps(filter_fake_context(value), ensure_ascii=False)
    for contact in (
        "candidate@example.invalid",
        "138-0000-0000",
        "010-12345678",
        "合成街道",
        "555-0100",
    ):
        assert contact not in filtered
    assert "2026-09" in filtered
    assert json.dumps(value, ensure_ascii=False) == original
