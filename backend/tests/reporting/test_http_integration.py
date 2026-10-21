"""通过现有 M2 路由注入 ReportService：成功导出与报告失败降级（T11/T23）。

本测试不修改 M2；它证明 A 可以按 `create_app(reporting=ReportService(...))`
接入本模块。M2 的 `task_error` 目前不识别 GatewayError/ReportError，因此失败
岗位的错误码会显示为 INTERNAL_ERROR（与 IN-03 记录的集成缺口相同），状态仍会
正确降级为 score_only，评分仍可导出。
"""

import asyncio
from uuid import uuid4

import httpx
import pytest

from app.llm import FakeModelDirectory, FakeModelGateway
from app.main import create_app
from app.reporting import ReportService
from app.settings import Settings

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


def gateway(failures=None) -> FakeModelGateway:
    return FakeModelGateway(
        FakeModelDirectory(),
        failures=failures,
        sleep=_no_sleep,
        clock=lambda: "2026-10-14T00:00:00Z",
    )


def app_for(service: ReportService):
    return create_app(Settings(_env_file=None), reporting=service)


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


async def run_graph(client):
    session = await client.post("/api/v1/session", json={"consent_version": "v1"})
    assert session.status_code == 200, session.text

    profile = (await post(client, "/api/v1/profiles", PROFILE)).json()
    await client.post(
        f"/api/v1/profiles/{profile['id']}/confirm", json={"version": profile["version"]}
    )

    accepted = (await post(client, "/api/v1/jobs", JOB)).json()
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
                "model_id": "demo-model-a",
            },
        )
    ).json()
    task = await poll(client, accepted["task_id"])
    diagnosis = (await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}")).json()
    return task, diagnosis


def test_report_service_drives_the_existing_diagnosis_and_export_routes():
    async def run():
        app = app_for(ReportService(gateway()))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Origin": ORIGIN},
        ) as client:
            task, diagnosis = await run_graph(client)
            assert task["status"] == "succeeded"
            item = diagnosis["items"][0]
            assert item["status"] == "succeeded"
            assert item["report"] is not None and item["error"] is None

            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("text/markdown")
            assert "### 规则评分" in exported.text
            assert "### AI 报告" in exported.text
            assert "总分：" in exported.text
            assert "模型选择：demo-model-a" in exported.text
        await app.state.platform.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "provider_unavailable"])
def test_report_failure_degrades_to_score_only_and_still_exports(failure):
    async def run():
        service = ReportService(gateway({"diagnosis_report": failure}), timeout_seconds=0.01)
        app = app_for(service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Origin": ORIGIN},
        ) as client:
            task, diagnosis = await run_graph(client)
            assert task["status"] == "partial"
            item = diagnosis["items"][0]
            assert item["status"] == "score_only"
            assert item["score_result"] is not None
            assert item["report"] is None and item["error"] is not None

            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert exported.status_code == 200
            assert "总分：" in exported.text
            assert "仅规则评分" in exported.text
            assert "AI 报告未生成" in exported.text
            assert "错误码：" in exported.text
        await app.state.platform.close()

    asyncio.run(run())
