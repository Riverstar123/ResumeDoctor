"""Expected graduation survives extraction/persistence without granting a degree."""

import asyncio
from datetime import date

import pytest

from app.contracts import JobContent, ProfileContent, Requirement
from app.database import create_app
from app.intake import IntakeError, validate_profile_content
from app.llm import FakeModelDirectory, FakeModelGateway
from app.platform.errors import ProfileValidationError, task_error
from app.platform.jobs.worker import create_worker
from app.platform.repositories.sqlite import SQLiteRepository, initialize_sqlite
from app.platform.validation import validate_profile
from app.scoring import assess_requirements
from app.settings import Settings
from tests.platform import test_int02
from tests.platform.test_api import check, session

TEXT = "合成教育经历：金融硕士，2024-09 至 2027-06，在读，预计毕业。"


def content(source_id="synthetic", source_type="message"):
    return ProfileContent.model_validate(
        {
            "overview": "合成在读档案",
            "as_of_month": "2026-11",
            "facts": [
                {
                    "id": "f1",
                    "kind": "education",
                    "label": "金融硕士",
                    "value": "master",
                    "polarity": "positive",
                    "application": "claimed",
                    "start_month": "2024-09",
                    "end_month": "2027-06",
                    "completed": False,
                    "evidence_ids": ["e1"],
                }
            ],
            "evidence": [
                {
                    "id": "e1",
                    "source_type": source_type,
                    "source_id": source_id,
                    "quote": TEXT,
                    "locator": None,
                }
            ],
        }
    )


def test_expected_graduation_passes_both_validators_without_rewriting_dates():
    profile = content()
    original = profile.model_dump()
    validate_profile_content(profile, {"synthetic": TEXT}, today=date(2026, 11, 5))
    validate_profile(profile, "2026-11")
    assert profile.model_dump() == original


@pytest.mark.parametrize(
    "updates",
    [
        {"completed": True},
        {"completed": None},
        {"kind": "experience", "value": None},
        {"kind": "project", "value": None},
        {"start_month": "2026-12"},
    ],
)
def test_other_future_dates_fail_with_safe_consistent_reason(updates):
    profile = content()
    profile.facts[0] = profile.facts[0].model_copy(update=updates)
    with pytest.raises(IntakeError) as extracted:
        validate_profile_content(profile, {"synthetic": TEXT}, today=date(2026, 11, 5))
    with pytest.raises(ProfileValidationError) as persisted:
        validate_profile(profile, "2026-11")
    for error in (extracted.value, persisted.value):
        public = task_error(error)
        assert public.code == "MODEL_OUTPUT_INVALID"
        assert public.details == {"reason_code": "FUTURE_END_DATE"}
        assert TEXT not in public.model_dump_json()
    assert (
        persisted.value.info.code == "VALIDATION_ERROR"
    )  # Direct manual edit remains input error.


def test_in_progress_degree_does_not_satisfy_completed_degree_requirement():
    requirement = Requirement(
        id="r1",
        quote="要求已取得硕士学位",
        category="education",
        importance="must",
        operator="degree_at_least",
        target="master",
        ignored=False,
        ignore_reason=None,
        subject=None,
    )
    job = JobContent(
        title="合成岗位", company_name=None, company_context="", requirements=[requirement]
    )
    result = assess_requirements(content(), job, "matcher-v1")
    assert result[0].status == "unknown"
    assert result[0].evidence_ids == ["e1"]


@pytest.mark.parametrize("completed", [False, True])
def test_docx_upload_worker_persistence_and_confirmation(tmp_path, monkeypatch, completed):
    monkeypatch.setattr(test_int02, "PROFILE_TEXT", TEXT)
    url = f"sqlite:///{tmp_path / 'graduation.sqlite3'}"
    initialize_sqlite(url)
    repo = SQLiteRepository(url)

    class EducationGateway(FakeModelGateway):
        async def _produce(self, task_name, prompt_context, behavior):
            assert task_name == "profile_extract"
            assert TEXT in prompt_context["source_text"]
            result = content(prompt_context["source_id"], "document")
            result.facts[0].completed = completed
            return result.model_dump(mode="json")

    settings = Settings(
        _env_file=None, llm_mode="fake", database_url=url, upload_dir=tmp_path / "uploads"
    )
    gateway = EducationGateway(FakeModelDirectory())
    app = create_app(settings, repository=repo, gateway=gateway)
    worker = create_worker(settings, repository=repo, gateway=gateway)

    async def run():
        async with test_int02.client_for(app) as client:
            await session(client)
            accepted = check(await test_int02.upload(client), 202, "TaskAccepted")
            task = await test_int02.finish(
                client, worker, accepted, status="failed" if completed else "succeeded"
            )
            if completed:
                assert task["error"]["code"] == "MODEL_OUTPUT_INVALID"
                assert task["error"]["details"] == {"reason_code": "FUTURE_END_DATE"}
                assert task["result"] is None
                return
            profile_id = task["result"]["resource_id"]
            profile = check(await client.get(f"/api/v1/profiles/{profile_id}"), 200, "Profile")
            assert profile["content"]["facts"][0]["end_month"] == "2027-06"
            assert profile["content"]["facts"][0]["completed"] is False
            assert profile["content"]["evidence"][0]["quote"] == TEXT
            assert profile["content"]["evidence"][0]["locator"]
            assert not profile["confirmed"]
            confirmed = check(
                await client.post(f"/api/v1/profiles/{profile_id}/confirm", json={"version": 1}),
                200,
                "Profile",
            )
            assert confirmed["confirmed"]
            assert confirmed["content"] == profile["content"]

    try:
        asyncio.run(run())
    finally:
        repo.close()
