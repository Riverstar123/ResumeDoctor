import asyncio
from copy import deepcopy

import pytest

from app.contracts import ProfileContent
from app.contracts.ports import TaskContext
from app.intake import GatewayIntake
from app.intake.privacy import filter_fake_context
from app.llm import FakeModelDirectory
from app.platform.demo_gateway import PROFILE_TEXT, IntegrationFakeGateway
from app.reporting.privacy import filter_report_context

UUID = "00000000-0000-4000-8000-13800000000a"


@pytest.mark.parametrize("filter_context", [filter_fake_context, filter_report_context])
@pytest.mark.parametrize(
    "identifier",
    [
        UUID,
        f"manual-{UUID}",
        f"{UUID}-e1",
        f"{UUID}bc",
        f"aa{UUID}bc",
        "id-a1b2c3d4-5678-90ef-abcd-13812345678abc-end",
    ],
)
def test_opaque_uuid_survives_while_actual_contacts_are_removed(filter_context, identifier):
    original = {
        "source_id": identifier,
        "evidence_ids": [identifier],
        "quote": "手机13800000000；邮箱 candidate@example.invalid",
    }
    before = deepcopy(original)
    filtered = filter_context(original)
    assert filtered["source_id"] == identifier and filtered["evidence_ids"] == [identifier]
    assert "13800000000" not in filtered["quote"]
    assert "candidate@example.invalid" not in filtered["quote"]
    assert original == before


@pytest.mark.parametrize("filter_context", [filter_fake_context, filter_report_context])
def test_phone_disguised_as_identifier_is_still_filtered(filter_context):
    assert filter_context({"source_id": "13800000000"}) == {"source_id": ""}


def test_deterministic_phone_shaped_uuid_does_not_break_intake_source_reference():
    async def no_sleep(_):
        pass

    gateway = IntegrationFakeGateway(FakeModelDirectory(), sleep=no_sleep)
    result = asyncio.run(
        GatewayIntake(gateway, source_id=UUID).advance_conversation(
            PROFILE_TEXT,
            ProfileContent(overview="", as_of_month="2026-09", facts=[], evidence=[]),
            [],
            context=TaskContext("demo-model-a"),
        )
    )
    assert {e.source_id for e in result.profile_content.evidence} == {UUID}
