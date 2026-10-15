"""PR #48: inherited facts need support, and private evidence can survive redaction."""

import asyncio
import json
from copy import deepcopy

import pytest
from jsonschema import validate

from app.contracts import Evidence, JobContent, Profile, ProfileContent, Requirement
from app.intake import GatewayIntake, IntakeError, synthetic_profile_content
from app.intake.privacy import filter_fake_context
from app.intake.validation import validate_profile_content
from app.scoring import MATCHER_VERSION, RULE_VERSION, ScoringService
from tests.intake.test_gateway_intake import CONTEXT, StubGateway, user_message


def run_profile(
    operation, gateway, previous, text="没有新增资料。", *, history=(), privacy_filter=None
):
    intake = GatewayIntake(gateway, source_id="new-user-source", privacy_filter=privacy_filter)
    if operation == "chat":
        return asyncio.run(
            intake.advance_conversation(text, previous, history, context=CONTEXT)
        ).profile_content
    saved = Profile(
        id="00000000-0000-4000-8000-000000000099",
        version=1,
        confirmed=True,
        content=previous,
        created_at="2026-10-15T00:00:00Z",
    )
    return asyncio.run(intake.build_profile(text, "document", saved, context=CONTEXT))


def payload_gateway(operation, content):
    if operation == "chat":
        return StubGateway(
            {"profile_chat": {"assistant_message": "请继续。", "profile_content": content}}
        )
    return StubGateway({"profile_extract": content})


@pytest.mark.parametrize("operation", ["chat", "build_profile"])
@pytest.mark.parametrize(
    ("index", "changes"),
    [
        (2, {"value": "doctorate"}),
        (0, {"kind": "skill"}),
        (0, {"label": "Kubernetes"}),
        (0, {"polarity": "negative"}),
        (1, {"application": "applied"}),
        (0, {"start_month": "2026-01", "end_month": "2026-09"}),
        (2, {"completed": False}),
        (2, {"evidence_ids": ["e1"]}),
    ],
    ids=["degree", "kind", "label", "polarity", "application", "dates", "completed", "refs"],
)
def test_old_fact_cannot_change_without_new_user_evidence(operation, index, changes):
    previous = synthetic_profile_content()
    original = previous.model_dump(mode="json")
    payload = deepcopy(original)
    payload["facts"][index].update(changes)

    with pytest.raises(IntakeError) as error:
        run_profile(operation, payload_gateway(operation, payload), previous)

    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert previous.model_dump(mode="json") == original


@pytest.mark.parametrize("operation", ["chat", "build_profile"])
def test_unrelated_new_evidence_does_not_authorize_old_fact_changes(operation):
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload["facts"][2]["value"] = "doctorate"
    payload["evidence"].append(
        Evidence(
            id="e-new",
            source_type="message" if operation == "chat" else "document",
            source_id="new-user-source",
            quote="我还了解 Docker。",
            locator=None,
        ).model_dump(mode="json")
    )

    with pytest.raises(IntakeError) as error:
        run_profile(operation, payload_gateway(operation, payload), previous, "我还了解 Docker。")

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_renaming_old_evidence_is_not_new_support_for_a_changed_fact():
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload["facts"][2].update(value="doctorate", evidence_ids=["e-renamed"])
    payload["evidence"].append({**payload["evidence"][2], "id": "e-renamed"})
    # The old source is still in the history window: quote validation alone is insufficient.
    source_text = previous.evidence[2].quote
    saved = Profile(
        id="00000000-0000-4000-8000-000000000099",
        version=1,
        confirmed=True,
        content=previous,
        created_at="2026-10-15T00:00:00Z",
    )

    with pytest.raises(IntakeError) as error:
        asyncio.run(
            GatewayIntake(
                payload_gateway("build_profile", payload),
                source_id=previous.evidence[2].source_id,
            ).build_profile(source_text, "manual", saved, context=CONTEXT)
        )

    assert error.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("operation", ["chat", "build_profile"])
def test_changed_fact_requires_a_genuine_quote_from_the_new_source(operation):
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload["facts"][2].update(value="doctorate", evidence_ids=["e-new"])
    payload["evidence"].append(
        Evidence(
            id="e-new",
            source_type="message" if operation == "chat" else "document",
            source_id="new-user-source",
            quote="我已取得博士学位。",
            locator=None,
        ).model_dump(mode="json")
    )

    with pytest.raises(IntakeError) as error:
        run_profile(operation, payload_gateway(operation, payload), previous)

    assert error.value.code == "QUOTE_NOT_IN_SOURCE"


def doctoral_score(content):
    job = JobContent(
        title="博士合成岗位",
        company_name=None,
        company_context="",
        requirements=[
            Requirement(
                id="r1",
                quote="必须具备博士学历。",
                category="education",
                importance="must",
                operator="degree_at_least",
                target="doctorate",
                ignored=False,
                ignore_reason=None,
                subject=None,
            )
        ],
    )
    service = ScoringService()
    assessments = service.assess_requirements(content, job, MATCHER_VERSION)
    return service.calculate_score(assessments, RULE_VERSION).score


@pytest.mark.parametrize("operation", ["chat", "build_profile"])
def test_user_can_correct_a_fact_with_new_verified_evidence(operation):
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    text = "更正学历：我已取得计算机博士学位。"
    payload["facts"][2].update(value="doctorate", evidence_ids=["e-new"])
    payload["evidence"].append(
        Evidence(
            id="e-new",
            source_type="message" if operation == "chat" else "document",
            source_id="new-user-source",
            quote=text,
            locator=None,
        ).model_dump(mode="json")
    )

    result = run_profile(operation, payload_gateway(operation, payload), previous, text)

    assert result.facts[2].value == "doctorate"
    assert result.evidence[:-1] == previous.evidence
    assert result.evidence[-1].quote == text
    assert doctoral_score(previous) == 0.0
    assert doctoral_score(result) == 100.0


def test_previously_unrecorded_user_history_can_support_a_correction():
    previous = synthetic_profile_content()
    message = user_message("我在课程项目中实际使用 SQL。", 1)
    payload = previous.model_dump(mode="json")
    payload["facts"][1].update(application="applied", evidence_ids=["e-new"])
    payload["evidence"].append(
        Evidence(
            id="e-new",
            source_type="message",
            source_id=message.id,
            quote=message.content,
            locator=None,
        ).model_dump(mode="json")
    )

    result = run_profile("chat", payload_gateway("chat", payload), previous, history=[message])

    assert result.facts[1].application == "applied"
    assert result.evidence[-1].source_id == message.id


class EchoPreviousGateway(StubGateway):
    """Return the snapshot visible to the model, subject to the actual frozen Schema."""

    async def generate_structured(
        self, task_name, prompt_context, output_schema, timeout_seconds, *, context
    ):
        content = deepcopy(
            prompt_context["profile_content"]
            if task_name == "profile_chat"
            else prompt_context["previous_profile"]["content"]
        )
        payload = (
            {"assistant_message": "请继续。", "profile_content": content}
            if task_name == "profile_chat"
            else content
        )
        validate(payload, output_schema)
        self.payloads[task_name] = payload
        return await super().generate_structured(
            task_name, prompt_context, output_schema, timeout_seconds, context=context
        )


@pytest.mark.parametrize("operation", ["chat", "build_profile"])
@pytest.mark.parametrize("contact", ["candidate@example.invalid", "13800000000"])
@pytest.mark.parametrize("response", ["original", "model-visible-projection"])
def test_contact_only_old_evidence_survives_continuation(operation, contact, response):
    previous = ProfileContent(
        overview="合成联系方式记录。",
        as_of_month="2026-09",
        facts=[],
        evidence=[
            Evidence(
                id="contact-e1",
                source_type="manual",
                source_id="contact-source",
                quote=contact,
                locator=None,
            )
        ],
    )
    validate_profile_content(previous, {"contact-source": contact})
    original = previous.model_dump(mode="json")
    gateway = (
        EchoPreviousGateway()
        if response == "model-visible-projection"
        else payload_gateway(operation, deepcopy(original))
    )

    result = run_profile(operation, gateway, previous)

    assert result == previous
    assert previous.model_dump(mode="json") == original
    sent = gateway.calls[0]["prompt_context"]
    assert contact not in json.dumps(sent, ensure_ascii=False)
    projection = (
        sent["profile_content"] if operation == "chat" else sent["previous_profile"]["content"]
    )
    assert projection["evidence"][0]["quote"]


@pytest.mark.parametrize("operation", ["chat", "build_profile"])
def test_redacted_quote_does_not_authorize_forged_old_evidence_metadata(operation):
    previous = synthetic_profile_content()
    previous.evidence[0].quote = "candidate@example.invalid"
    payload = previous.model_dump(mode="json")
    payload["evidence"][0].update(quote="[联系方式已过滤]", source_id="forged-source")

    with pytest.raises(IntakeError) as error:
        run_profile(operation, payload_gateway(operation, payload), previous)

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_contact_projection_uses_the_explicit_policy_once():
    previous = synthetic_profile_content()
    previous.evidence[0].quote = "candidate@example.invalid"
    gateway = EchoPreviousGateway()
    gateway.is_fake = False  # Local stub only; this never calls a real provider.
    calls = []

    def policy(value):
        calls.append(value)
        return filter_fake_context(value)

    result = run_profile("chat", gateway, previous, privacy_filter=policy)

    assert result == previous
    assert len(calls) == 1
    assert "candidate@example.invalid" not in json.dumps(gateway.calls[0]["prompt_context"])


def test_new_evidence_cannot_use_a_redaction_marker_instead_of_user_text():
    previous = synthetic_profile_content()
    payload = previous.model_dump(mode="json")
    payload["evidence"].append(
        Evidence(
            id="e-new",
            source_type="message",
            source_id="new-user-source",
            quote="[联系方式已过滤]",
            locator=None,
        ).model_dump(mode="json")
    )

    with pytest.raises(IntakeError) as error:
        run_profile("chat", payload_gateway("chat", payload), previous)

    assert error.value.code == "QUOTE_NOT_IN_SOURCE"
