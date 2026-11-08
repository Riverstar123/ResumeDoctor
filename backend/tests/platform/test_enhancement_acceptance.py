"""Independent local acceptance: optional enhancement cannot own base availability."""

import asyncio
from copy import deepcopy

from app.contracts import ReportContent
from app.contracts.models import Action
from app.platform.catalog import FakeModelCatalog
from app.platform.errors import PlatformError
from app.platform.fakes import FakeReporting
from app.reporting.explanation import assemble_report

from .test_api import app_for, check, clients, graph, poll, post, session


class ObservedReporting(FakeReporting):
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    @staticmethod
    def build_base_report(profile, job, score):
        return ReportContent.model_validate(
            assemble_report({"suggestions": [], "actions": []}, score)
        )

    async def generate_enhancement(
        self, profile, job, score, metadata, *, context, requirement_ids=None
    ):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise PlatformError(422, "MODEL_OUTPUT_INVALID", "synthetic enhancement rejection")
        base = self.build_base_report(profile, job, score)
        base.actions = [
            Action(
                requirement_id=score.assessments[0].requirement_id,
                priority="P1",
                horizon="now",
                task="核对该要求对应的原文",
                done_when="已核对并确认材料",
            )
        ]
        return base


def test_base_still_completes_without_a_report_model_and_never_calls_enhancement():
    async def run():
        reporting, catalog = ObservedReporting(), FakeModelCatalog()
        async with clients(app_for(reporting=reporting, catalog=catalog)) as (client,):
            await session(client)
            prepared = await graph(client)
            catalog.disabled.update({"demo-model-a", "demo-model-b"})
            body = {key: value for key, value in prepared["body"].items() if key != "model_id"}
            accepted = check(
                await post(client, "/api/v1/diagnoses", body), 202, "DiagnosisAccepted"
            )
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "succeeded"
            path = f"/api/v1/diagnoses/{accepted['diagnosis_id']}"
            diagnosis = check(await client.get(path), 200, "Diagnosis")
            item = diagnosis["items"][0]
            assert item["report"] is not None and item["status"] == "succeeded"
            assert item["report"]["suggestions"] == [] and item["report"]["actions"] == []
            assert item["model_metadata"] is None and diagnosis["model_id"] is None
            assert reporting.calls == 0
            exported = await client.get(path + "/export")
            assert exported.status_code == 200
            assert item["report"]["summary"] in exported.text

    asyncio.run(run())


def test_enhancement_reuses_inflight_and_completed_tasks_and_base_remains_readable():
    async def run():
        reporting = ObservedReporting()
        async with clients(app_for(reporting=reporting), count=2) as (client, stranger):
            await session(client)
            await session(stranger)
            prepared = await graph(client)
            diagnosis = prepared["diagnosis"]
            item = diagnosis["items"][0]
            path = f"/api/v1/diagnoses/{diagnosis['id']}"
            endpoint = f"{path}/items/{item['id']}/enhancements"
            before = deepcopy(item)
            reporting.release.clear()
            body = {"model_id": "demo-model-a", "requirement_ids": []}
            accepted = check(await post(client, endpoint, body), 202, "TaskAccepted")
            await asyncio.wait_for(reporting.started.wait(), timeout=2)
            duplicate = check(await post(client, endpoint, body), 202, "TaskAccepted")
            assert duplicate["task_id"] == accepted["task_id"]
            visible = check(await client.get(path), 200, "Diagnosis")["items"][0]
            assert visible["report"] == before["report"] and visible["status"] == "succeeded"
            assert (await client.get(path + "/export")).status_code == 200
            check(await post(stranger, endpoint, body), 404)
            assert reporting.calls == 1
            reporting.release.set()
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] in {"succeeded", "partial"}
            complete = check(await client.get(path), 200, "Diagnosis")["items"][0]
            assert complete["score_result"] == before["score_result"]
            for field in ("summary", "gaps"):
                assert complete["report"][field] == before["report"][field]
            assert complete["report"]["actions"]
            repeated = check(await post(client, endpoint, body), 202, "TaskAccepted")
            assert repeated["task_id"] == accepted["task_id"] and reporting.calls == 1

    asyncio.run(run())


def test_failed_new_enhancement_preserves_successful_content_and_cannot_retry_by_new_key():
    async def run():
        reporting = ObservedReporting()
        async with clients(app_for(reporting=reporting)) as (client,):
            await session(client)
            prepared = await graph(client)
            diagnosis = prepared["diagnosis"]
            item = diagnosis["items"][0]
            path = f"/api/v1/diagnoses/{diagnosis['id']}"
            endpoint = f"{path}/items/{item['id']}/enhancements"
            first = check(
                await post(client, endpoint, {"model_id": "demo-model-a"}), 202, "TaskAccepted"
            )
            await poll(client, first["task_id"])
            before = check(await client.get(path), 200, "Diagnosis")["items"][0]
            reporting.fail = True
            failed = check(
                await post(client, endpoint, {"model_id": "demo-model-b"}), 202, "TaskAccepted"
            )
            task, _ = await poll(client, failed["task_id"])
            assert task["status"] == "failed"
            after = check(await client.get(path), 200, "Diagnosis")
            assert after["status"] == "succeeded"
            assert after["items"][0]["status"] == "succeeded"
            assert after["items"][0]["report"] == before["report"]
            assert after["items"][0]["score_result"] == before["score_result"]
            assert after["items"][0]["enhancement"]["status"] == "failed"
            repeated = check(
                await post(client, endpoint, {"model_id": "demo-model-b"}), 202, "TaskAccepted"
            )
            assert repeated["task_id"] == failed["task_id"] and reporting.calls == 2
            assert (await client.get(path + "/export")).status_code == 200

    asyncio.run(run())
