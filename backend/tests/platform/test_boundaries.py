"""Additional HTTP tests for transaction safety and injected port failures."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.contracts import JobContent
from app.contracts.ports import ConversationResult
from app.platform.fakes import FakeIntake, FakeReporting, FakeScoring
from app.platform.repositories import InMemoryRepository
from app.settings import Settings

from .test_api import JOB, PROFILE, app_for, check, clients, graph, poll, post, session


def test_invalid_conversation_output_is_atomic():
    class InvalidIntake(FakeIntake):
        async def advance_conversation(
            self, user_text, profile_content, history_user_messages, *, context
        ):
            return ConversationResult(123, profile_content)  # Runtime-invalid port output.

    async def run():
        app = app_for(intake=InvalidIntake())
        async with clients(app) as (client,):
            await session(client)
            profile = check(await post(client, "/api/v1/profiles", PROFILE), 201, "Profile")
            pid = profile["id"]
            accepted = check(
                await post(
                    client,
                    f"/api/v1/profiles/{pid}/messages",
                    {
                        "base_version": 1,
                        "content": "synthetic-round",
                        "model_id": "demo-model-a",
                    },
                ),
                202,
                "TaskAccepted",
            )
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["error"]["code"] == "MODEL_OUTPUT_INVALID"
            assert check(await client.get(f"/api/v1/profiles/{pid}"), 200, "Profile") == profile
            assert (
                check(await client.get(f"/api/v1/profiles/{pid}/messages"), 200, "MessageList")[
                    "items"
                ]
                == []
            )

    asyncio.run(run())


def test_invalid_constructed_dto_does_not_log_serializer_inputs(recwarn, caplog):
    class InvalidIntake(FakeIntake):
        async def extract_job(self, *args, **kwargs):
            return JobContent.model_construct(
                title={"secret": "synthetic-serializer-secret"},
                company_name=None,
                company_context="",
                requirements=[],
            )

    async def run():
        app = app_for(intake=InvalidIntake())
        async with clients(app) as (client,):
            await session(client)
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            assert task["error"]["code"] == "MODEL_OUTPUT_INVALID"
            assert "synthetic-serializer-secret" not in str(task)

    asyncio.run(run())
    assert not recwarn.list
    assert "synthetic-serializer-secret" not in caplog.text


@pytest.mark.parametrize("stage,expected", [("report", "partial"), ("score", "failed")])
def test_invalid_port_outputs_do_not_break_polling(stage, expected):
    class InvalidReport(FakeReporting):
        async def generate_report(self, *args, **kwargs):
            return {"summary": "missing-required-fields"}

    class InvalidScoring(FakeScoring):
        def calculate_score(self, assessments, rule_version):
            score = super().calculate_score(assessments, rule_version)
            score.assessments[0].evidence_ids = ["not-in-frozen-profile"]
            return score

    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            ready = await graph(client)
            if stage == "report":
                app.state.platform.reporting = InvalidReport()
            else:
                app.state.platform.scoring = InvalidScoring()
            accepted = check(
                await post(client, "/api/v1/diagnoses", ready["body"]), 202, "DiagnosisAccepted"
            )
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == expected
            diagnosis = check(
                await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}"), 200, "Diagnosis"
            )
            item = diagnosis["items"][0]
            assert item["error"]["code"] == "MODEL_OUTPUT_INVALID"
            assert bool(item["score_result"]) == (stage == "report")
            if stage == "score":
                assert task["error"]
                check(
                    await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export"),
                    409,
                    code="NOT_READY",
                )

    asyncio.run(run())


def test_total_timeout_and_not_ready_export():
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            ready = await graph(client)
            app.state.platform.executor.gate = asyncio.Event()
            app.state.platform.task_timeout_seconds = 0.02
            accepted = check(
                await post(client, "/api/v1/diagnoses", ready["body"]), 202, "DiagnosisAccepted"
            )
            check(
                await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}/export"),
                409,
                code="NOT_READY",
            )
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["error"]["code"] == "TASK_TIMEOUT"
            diagnosis = check(
                await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}"), 200, "Diagnosis"
            )
            assert (
                diagnosis["status"] == "failed"
                and diagnosis["items"][0]["error"]["code"] == "TASK_TIMEOUT"
            )

    asyncio.run(run())


def test_request_rate_and_idempotency_retention():
    async def run():
        current = [datetime(2026, 10, 12, tzinfo=UTC)]
        app = app_for(repository=InMemoryRepository(clock=lambda: current[0]))
        async with clients(app) as (client,):
            await session(client)
            key = "synthetic-idempotency-key-24h"
            first = check(await post(client, "/api/v1/profiles", PROFILE, key=key), 201, "Profile")
            for _ in range(18):
                check(await post(client, "/api/v1/profiles", PROFILE, key=key), 201, "Profile")
            response = await post(client, "/api/v1/profiles", PROFILE, key=key)
            check(response, 429, code="RATE_LIMITED")
            assert response.headers["Retry-After"] == "60"
            assert "Retry-After" in response.headers["Access-Control-Expose-Headers"]
            current[0] += timedelta(seconds=61)
            assert (
                check(await post(client, "/api/v1/profiles", PROFILE, key=key), 201, "Profile")
                == first
            )
            current[0] += timedelta(hours=24)
            assert (
                check(await post(client, "/api/v1/profiles", PROFILE, key=key), 201, "Profile")[
                    "id"
                ]
                != first["id"]
            )

    asyncio.run(run())


def test_http_internal_errors_are_sanitized(caplog):
    class BrokenCatalog:
        def list_models(self):
            raise RuntimeError("synthetic-provider-key /private/raw-resume-path")

    async def run():
        app = app_for(catalog=BrokenCatalog())
        async with clients(app) as (client,):
            await session(client)
            response = await client.get("/api/v1/models")
            check(response, 500, code="INTERNAL_ERROR")
            assert "synthetic-provider-key" not in response.text
            assert response.json()["request_id"] == response.headers["X-Request-ID"]

    asyncio.run(run())
    assert "synthetic-provider-key" not in caplog.text and "raw-resume-path" not in caplog.text


@pytest.mark.parametrize(
    "origin", ["*", "https://*.example.test", "https://test/path", "https://user:password@test"]
)
def test_wildcard_and_non_origin_settings_are_rejected(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_origins=[origin])


def test_model_mapping_and_profile_snapshot_are_frozen_while_running():
    class SpyReport(FakeReporting):
        observed = []

        async def generate_report(
            self, profile_snapshot, job_snapshot, score_result, model_metadata, *, context
        ):
            self.observed.append(
                (profile_snapshot.version, context.model_id, model_metadata.provider)
            )
            return await super().generate_report(
                profile_snapshot, job_snapshot, score_result, model_metadata, context=context
            )

    async def run():
        spy = SpyReport()
        app = app_for(reporting=spy)
        async with clients(app) as (client,):
            await session(client)
            ready = await graph(client)
            executor = app.state.platform.executor
            executor.gate = asyncio.Event()
            accepted = check(
                await post(
                    client, "/api/v1/diagnoses", {**ready["body"], "model_id": "demo-model-b"}
                ),
                202,
                "DiagnosisAccepted",
            )
            app.state.platform.catalog.models.items[1].provider = "changed-after-enqueue"
            pid = ready["profile"]["id"]
            check(
                await client.put(
                    f"/api/v1/profiles/{pid}",
                    json={"base_version": 1, "content": PROFILE["content"]},
                ),
                200,
                "Profile",
            )
            executor.gate.set()
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "succeeded"
            assert spy.observed[-1] == (1, "demo-model-b", "fake")

    asyncio.run(run())


def test_six_jobs_and_empty_jd_are_rejected():
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            ready = await graph(client)
            check(
                await post(client, "/api/v1/jobs", {**JOB, "raw_text": "   "}),
                422,
                code="VALIDATION_ERROR",
            )
            check(
                await post(
                    client,
                    "/api/v1/diagnoses",
                    {**ready["body"], "jobs": ready["body"]["jobs"] * 6},
                ),
                422,
                code="VALIDATION_ERROR",
            )

    asyncio.run(run())


def test_overlong_min_months_is_422_without_creating_a_version(caplog):
    async def run():
        app = app_for()
        async with clients(app) as (client,):
            await session(client)
            accepted = check(await post(client, "/api/v1/jobs", JOB), 202, "TaskAccepted")
            task, _ = await poll(client, accepted["task_id"])
            jid = task["result"]["resource_id"]
            job = check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job")
            content = job["content"]
            requirement = content["requirements"][0]
            requirement.update(operator="min_months", subject="Python", target="9" * 4301)
            response = await client.put(
                f"/api/v1/jobs/{jid}",
                json={"base_version": 1, "raw_text": job["raw_text"], "content": content},
            )
            check(response, 422, code="VALIDATION_ERROR")
            assert requirement["target"] not in response.text
            unchanged = check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job")
            assert unchanged["version"] == 1
            assert unchanged["content"]["requirements"][0]["operator"] == "manual_review"
            assert check(await client.get(f"/api/v1/jobs/{jid}?version=1"), 200, "Job") == unchanged
            check(await client.get(f"/api/v1/jobs/{jid}?version=2"), 404, code="RESOURCE_NOT_FOUND")
            # Ordinary positive integers still use the unchanged HTTP contract.
            requirement["target"] = "12"
            updated = check(
                await client.put(
                    f"/api/v1/jobs/{jid}",
                    json={"base_version": 1, "raw_text": job["raw_text"], "content": content},
                ),
                200,
                "Job",
            )
            assert updated["version"] == 2
            assert updated["content"]["requirements"][0]["target"] == "12"

    asyncio.run(run())
    assert "9" * 4301 not in caplog.text
