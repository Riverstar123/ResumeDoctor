"""Local ASGI + synthetic provider replay: base report survives enhancement failures."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.llm import FakeModelDirectory, FakeModelGateway, build_llm
from app.main import create_app
from app.platform.integration import GatewayCatalog
from app.reporting import ReportService
from app.reporting.privacy import filter_report_context
from app.settings import Settings
from tests.llm.test_real_gateway import ok, real_settings

ORIGIN = "http://localhost:5173"
PROFILE = {
    "content": {
        "overview": "完全虚构的报告联调档案。",
        "as_of_month": "2026-09",
        "facts": [],
        "evidence": [],
    }
}
JOB = {"raw_text": "合成 JD：需要 Python。", "company_context": "", "model_id": "demo-model-a"}


async def _no_sleep(_seconds: float) -> None:
    return None


def gateway(directory: FakeModelDirectory, failures=None) -> FakeModelGateway:
    return FakeModelGateway(
        directory,
        failures=failures,
        sleep=_no_sleep,
        clock=lambda: "2026-10-14T00:00:00Z",
    )


def app_for(service: ReportService, directory: FakeModelDirectory):
    # 目录是任务冻结元数据和网关实际映射的共同来源，应用装配必须共用同一个。
    return create_app(
        Settings(_env_file=None), catalog=GatewayCatalog(directory), reporting=service
    )


async def post(client, path, body):
    return await client.post(path, json=body, headers={"Idempotency-Key": str(uuid4())})


async def poll(client, task_id):
    for _ in range(200):
        response = await client.get(f"/api/v1/tasks/{task_id}")
        task = response.json()
        if task["status"] in {"succeeded", "partial", "failed"}:
            return task
        await asyncio.sleep(0.005)
    raise AssertionError("task did not reach a terminal state")


async def run_graph(client, model_id="demo-model-a", *, profile_body=None, job_body=None):
    session = await client.post("/api/v1/session", json={"consent_version": "v1"})
    assert session.status_code == 200, session.text

    profile = (await post(client, "/api/v1/profiles", profile_body or PROFILE)).json()
    await client.post(
        f"/api/v1/profiles/{profile['id']}/confirm", json={"version": profile["version"]}
    )

    accepted = (
        await post(client, "/api/v1/jobs", {**(job_body or JOB), "model_id": model_id})
    ).json()
    job_task = await poll(client, accepted["task_id"])
    assert job_task["status"] == "succeeded", job_task
    job_id = job_task["result"]["resource_id"]
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    await client.post(f"/api/v1/jobs/{job_id}/confirm", json={"version": job["version"]})

    accepted = (
        await post(
            client,
            "/api/v1/diagnoses",
            {
                "profile": {"id": profile["id"], "version": profile["version"]},
                "jobs": [{"id": job_id, "version": job["version"]}],
                "model_id": model_id,
            },
        )
    ).json()
    task = await poll(client, accepted["task_id"])
    diagnosis = (await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}")).json()
    return task, diagnosis


async def enhance(client, diagnosis, model_id="demo-model-a"):
    item = diagnosis["items"][0]
    response = await post(
        client,
        f"/api/v1/diagnoses/{diagnosis['id']}/items/{item['id']}/enhancements",
        {"model_id": model_id},
    )
    assert response.status_code == 202, response.text
    task = await poll(client, response.json()["task_id"])
    updated = (await client.get(f"/api/v1/diagnoses/{diagnosis['id']}")).json()
    return task, updated


def test_base_report_and_export_need_no_model_call():
    async def run():
        directory = FakeModelDirectory()
        model = gateway(directory, {"diagnosis_report": "provider_unavailable"})
        app = app_for(ReportService(model), directory)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Origin": ORIGIN},
        ) as client:
            task, diagnosis = await run_graph(client)
            assert task["status"] == "succeeded" and not model.calls
            item = diagnosis["items"][0]
            assert item["report"] and item["error"] is None and item["model_metadata"] is None
            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert exported.status_code == 200
            assert "基础诊断" in exported.text and "总分：" in exported.text
            assert "实际模型" not in exported.text and "AI 报告未生成" not in exported.text
        await app.state.platform.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "provider_unavailable"])
def test_enhancement_failure_preserves_complete_base_and_export(failure):
    async def run():
        directory = FakeModelDirectory()
        service = ReportService(
            gateway(directory, {"diagnosis_report": failure}), timeout_seconds=0.01
        )
        app = app_for(service, directory)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Origin": ORIGIN},
        ) as client:
            _, diagnosis = await run_graph(client)
            original = diagnosis["items"][0]
            task, updated = await enhance(client, diagnosis)
            item = updated["items"][0]
            assert task["status"] == "failed" and item["enhancement"]["status"] == "failed"
            assert item["status"] == updated["status"] == "succeeded"
            assert (
                item["score_result"] == original["score_result"]
                and item["report"] == original["report"]
            )
            assert item["error"] is None and item["enhancement"]["error"]
            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert "总分：" in exported.text and "基础报告仍可使用" in exported.text
            assert "AI 报告未生成" not in exported.text
        await app.state.platform.close()

    asyncio.run(run())


def test_direct_analysis_survives_persistence_and_export(snapshots):
    async def run():
        from app.platform.fakes import FakeIntake
        from app.scoring import ScoringService

        profile, job, _ = snapshots
        requests = []

        async def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            return ok(
                {
                    "summary": "AI已结合岗位原文分析，建议突出项目实践。",
                    "gaps": [],
                    "actions": [
                        {
                            "requirement_id": "r1",
                            "priority": "P0",
                            "horizon": "now",
                            "task": "将项目工具写进经历段落。",
                            "done_when": "经历中体现工具与用途。",
                        }
                    ],
                    "suggestions": [
                        {
                            "requirement_id": "r1",
                            "original": profile.content.evidence[0].quote,
                            "revised": "面向岗位整理项目经历。",
                            "rationale": "突出相关性。",
                            "evidence_ids": [profile.content.evidence[0].id],
                            "requires_user_input": False,
                        }
                    ],
                }
            )

        components = build_llm(real_settings(), transport=httpx.MockTransport(handler))
        app = app_for(
            ReportService(components.gateway, privacy_filter=filter_report_context),
            components.directory,
        )

        class FixtureIntake(FakeIntake):
            async def extract_job(self, *args, **kwargs):
                return job.content.model_copy(deep=True)

        app.state.platform.intake = FixtureIntake()
        app.state.platform.scoring = ScoringService()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Origin": ORIGIN},
        ) as client:
            task, diagnosis = await run_graph(
                client,
                "real-default",
                profile_body={"content": profile.content.model_dump()},
                job_body={**JOB, "raw_text": job.raw_text},
            )
            assert task["status"] == "succeeded" and not requests
            original = diagnosis["items"][0]
            task, updated = await enhance(client, diagnosis, "real-default")
            item = updated["items"][0]
            assert item["status"] == updated["status"] == "succeeded"
            assert item["score_result"] == original["score_result"]
            assert item["report"]["summary"].startswith("AI已结合")
            assert item["report"]["gaps"] == []
            assert item["report"]["actions"] and item["report"]["suggestions"]
            assert item["enhancement"]["status"] == "succeeded" and len(requests) == 1
            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert "AI已结合" in exported.text and "面向岗位整理项目经历" in exported.text
        await app.state.platform.close()

    asyncio.run(run())
