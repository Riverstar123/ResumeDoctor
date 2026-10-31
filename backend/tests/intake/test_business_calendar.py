import asyncio
from datetime import date, datetime

import pytest

import app.business_calendar as calendar
from app.contracts import ProfileContent
from app.intake import GatewayIntake, IntakeError
from tests.intake.test_gateway_intake import CONTEXT, StubGateway, chat_payload


@pytest.mark.parametrize("operation", ["profile_chat", "profile_extract"])
@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize("today", [None, date(2026, 10, 31)])
def test_prompt_and_draft_validation_share_business_date(monkeypatch, operation, future, today):
    instant = datetime.fromisoformat("2026-10-31T16:00:00+00:00")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(calendar, "datetime", FrozenDateTime)
    month = "2026-10" if today else "2026-11"
    future_month = "2026-11" if today else "2026-12"
    text = "我使用 Python 完成课程项目。"
    payload = chat_payload(text)
    payload["profile_content"]["as_of_month"] = future_month if future else month
    if operation == "profile_extract":
        payload["profile_content"]["evidence"][0]["source_type"] = "document"
    gateway = StubGateway(
        {operation: payload if operation == "profile_chat" else payload["profile_content"]}
    )
    intake = GatewayIntake(gateway, today=today)

    async def run():
        if operation == "profile_chat":
            previous = ProfileContent(overview="", as_of_month=month, facts=[], evidence=[])
            return (
                await intake.advance_conversation(text, previous, [], context=CONTEXT)
            ).profile_content
        return await intake.build_profile(text, "document", context=CONTEXT)

    if future:
        with pytest.raises(IntakeError) as error:
            asyncio.run(run())
        assert error.value.code == "AS_OF_MONTH_IN_FUTURE"
    else:
        assert asyncio.run(run()).as_of_month == month
    assert gateway.calls[0]["prompt_context"]["current_month"] == month
