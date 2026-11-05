"""New writes reject contradictory education state without rewriting sources."""

from datetime import date

import pytest

from app.contracts import ProfileContent
from app.intake import IntakeError, validate_profile_content
from app.platform.errors import ProfileValidationError
from app.platform.validation import validate_profile


def education(completed, states):
    quote = "合成学历状态：" + "、".join(states)
    return ProfileContent.model_validate(
        {
            "overview": "合成",
            "as_of_month": "2026-11",
            "facts": [
                {
                    "id": "f1",
                    "kind": "education",
                    "label": "合成学历",
                    "value": "master",
                    "polarity": "positive",
                    "application": "claimed",
                    "start_month": "2023-09",
                    "end_month": "2025-06",
                    "completed": completed,
                    "evidence_ids": ["e1"],
                    "attributes": [
                        {"name": "enrollment", "value": state, "quote": quote} for state in states
                    ],
                }
            ],
            "evidence": [
                {
                    "id": "e1",
                    "source_type": "manual",
                    "source_id": "synthetic",
                    "quote": quote,
                    "locator": None,
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "completed,states",
    [(True, ["enrolled"]), (False, ["completed"]), (None, ["enrolled", "completed"])],
)
def test_intake_and_persistence_reject_mutually_exclusive_states(completed, states):
    p = education(completed, states)
    original = p.model_dump()
    with pytest.raises(IntakeError, match="学历完成状态与在读属性矛盾"):
        validate_profile_content(p, {"synthetic": p.evidence[0].quote}, today=date(2026, 11, 5))
    with pytest.raises(ProfileValidationError) as rejected:
        validate_profile(p, "2026-11")
    assert rejected.value.info.code == "VALIDATION_ERROR"
    assert "学历完成状态与在读属性矛盾" in rejected.value.info.message
    assert p.model_dump() == original


@pytest.mark.parametrize(
    "completed,states",
    [
        (True, ["completed"]),
        (False, ["enrolled"]),
        (None, ["completed"]),
        (None, ["enrolled"]),
        (True, []),
        (False, []),
    ],
)
def test_compatible_or_unspecified_states_remain_editable(completed, states):
    p = education(completed, states)
    validate_profile_content(p, {"synthetic": p.evidence[0].quote}, today=date(2026, 11, 5))
    validate_profile(p, "2026-11")


def test_profile_create_and_edit_reject_state_conflict_without_saving_a_new_version():
    import asyncio

    from tests.platform.test_api import app_for, check, clients, post, session

    async def run():
        async with clients(app_for()) as (client,):
            await session(client)
            p = education(False, ["enrolled"])
            original = p.model_dump(mode="json")
            saved = check(
                await post(client, "/api/v1/profiles", {"content": original}), 201, "Profile"
            )
            p.facts[0].completed = True
            body = p.model_dump(mode="json")
            for response in (
                await post(client, "/api/v1/profiles", {"content": body}),
                await client.put(
                    f"/api/v1/profiles/{saved['id']}", json={"base_version": 1, "content": body}
                ),
            ):
                error = check(response, 422, code="VALIDATION_ERROR")["error"]
                assert "学历完成状态与在读属性矛盾" in error["message"]
            current = check(await client.get(f"/api/v1/profiles/{saved['id']}"), 200, "Profile")
            assert current["version"] == 1 and current["content"] == original

    asyncio.run(run())
