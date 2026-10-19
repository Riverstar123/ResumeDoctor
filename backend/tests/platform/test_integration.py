"""INT-01 consumer tests over C fixtures, real M4 scoring and E's fake gateway."""

import asyncio
import copy

import pytest

from app.intake import (
    KUBERNETES_JOB_RAW_TEXT,
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCE_TEXT,
    SyntheticIntake,
)
from app.integration import create_app
from app.llm import FakeModelDirectory, FakeModelGateway
from app.platform.fakes import FakeTaskExecutor
from app.scoring import ScoringService
from app.settings import Settings
from app.tools.check_contracts import compare_routes, load_design

from .test_api import PROFILE, check, clients, poll, post, session

SECOND_JD = KUBERNETES_JOB_RAW_TEXT


async def extracted_job(client, raw_text=SYNTHETIC_JOB_RAW_TEXT, *, company_context=""):
    accepted = check(
        await post(
            client,
            "/api/v1/jobs",
            {
                "raw_text": raw_text,
                "company_context": company_context,
                "model_id": "demo-model-a",
            },
        ),
        202,
        "TaskAccepted",
    )
    task, _ = await poll(client, accepted["task_id"])
    return task


async def confirmed_profile(client):
    await session(client)
    profile = check(await post(client, "/api/v1/profiles", PROFILE), 201, "Profile")
    pid = profile["id"]
    accepted = check(
        await post(
            client,
            f"/api/v1/profiles/{pid}/messages",
            {
                "base_version": 1,
                "content": SYNTHETIC_SOURCE_TEXT,
                "model_id": "demo-model-a",
            },
        ),
        202,
        "TaskAccepted",
    )
    task, _ = await poll(client, accepted["task_id"])
    assert task["status"] == "succeeded"
    return check(
        await client.post(
            f"/api/v1/profiles/{pid}/confirm",
            json={
                "version": task["result"]["version"],
            },
        ),
        200,
        "Profile",
    )


async def prepared(client):
    """Canonical extraction plus explicit USER edit, separate from two-input acceptance."""
    profile = await confirmed_profile(client)
    pid = profile["id"]
    jobs = []
    for index in range(2):
        task = await extracted_job(client)
        assert task["status"] == "succeeded"
        jid = task["result"]["resource_id"]
        job = check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job")
        if index:
            content = copy.deepcopy(job["content"])
            content["title"] = "[演示数据] 用户手工修正的 Docker 岗位"
            content["requirements"] = [content["requirements"][2]]
            content["requirements"][0]["id"] = "docker-only"
            job = check(
                await client.put(
                    f"/api/v1/jobs/{jid}",
                    json={
                        "base_version": 1,
                        "raw_text": "熟悉 Docker 优先。",
                        "content": content,
                    },
                ),
                200,
                "Job",
            )
        jobs.append(
            check(
                await client.post(
                    f"/api/v1/jobs/{jid}/confirm",
                    json={
                        "version": job["version"],
                    },
                ),
                200,
                "Job",
            )
        )
    body = {
        "profile": {"id": pid, "version": profile["version"]},
        "jobs": [{"id": j["id"], "version": j["version"]} for j in jobs],
        "model_id": "demo-model-a",
    }
    return profile, jobs, body


async def diagnose(client, body):
    accepted = check(await post(client, "/api/v1/diagnoses", body), 202, "DiagnosisAccepted")
    task, _ = await poll(client, accepted["task_id"])
    diagnosis = check(
        await client.get(f"/api/v1/diagnoses/{accepted['diagnosis_id']}"), 200, "Diagnosis"
    )
    return task, diagnosis


def test_real_calculator_two_frozen_jobs_model_switch_and_export(monkeypatch):
    calls = []
    calculate = ScoringService.calculate_score

    def tracked(self, assessments, rule_version):
        calls.append([a.requirement_id for a in assessments])
        return calculate(self, assessments, rule_version)

    monkeypatch.setattr(ScoringService, "calculate_score", tracked)

    async def run():
        app = create_app(Settings(_env_file=None))
        assert isinstance(app.state.platform.intake, SyntheticIntake)
        assert isinstance(app.state.platform.scoring, ScoringService)
        assert compare_routes(load_design(), app.openapi())["pending"] == []
        async with clients(app) as (client,):
            profile, jobs, body = await prepared(client)
            models = check(await client.get("/api/v1/models"), 200, "ModelList")
            assert models == app.state.gateway.directory.list_models().model_dump(mode="json")
            assert all(m["provider"] == "fake" for m in models["items"])
            task, diagnosis = await diagnose(client, body)
            assert task["status"] == "succeeded"
            first, second = diagnosis["items"]
            # docs/05-scoring.md hand calculation, not a hardcoded production score.
            score = first["score_result"]
            assert score["score"] == 66.7 and score["unknown_weight_ratio"] == 0.1667
            assert {d["category"]: d["score"] for d in score["dimensions"]} == {
                "skill": 60.0,
                "education": 100.0,
            }
            assert second["score_result"]["score"] == 0
            assert [a["requirement_id"] for a in second["score_result"]["assessments"]] == [
                "docker-only",
            ]
            assert {g["requirement_id"] for g in second["report"]["gaps"]} == {"docker-only"}
            assert second["report"] != first["report"]
            assert [i["job"] for i in diagnosis["items"]] == body["jobs"]
            assert all("演示数据" in i["report"]["summary"] for i in diagnosis["items"])
            assert all(i["model_metadata"]["provider"] == "fake" for i in diagnosis["items"])
            saved = copy.deepcopy(diagnosis)
            body["model_id"] = "demo-model-b"
            _, other = await diagnose(client, body)
            assert [i["score_result"] for i in other["items"]] == [
                i["score_result"] for i in diagnosis["items"]
            ]
            assert all(i["model_metadata"]["model_id"] == "demo-model-b" for i in other["items"])
            unchanged = check(
                await client.get(f"/api/v1/diagnoses/{saved['id']}"), 200, "Diagnosis"
            )
            assert unchanged == saved
            text = (await client.get(f"/api/v1/diagnoses/{saved['id']}/export")).text
            assert "66.7" in text and "docker-only" in text and "演示数据" in text
            assert profile["id"] in text
        assert len(app.state.gateway.calls) == 4
        assert all(c.task_name == "diagnosis_report" for c in app.state.gateway.calls)
        assert calls == [["r1", "r2", "r3", "r4"], ["docker-only"]] * 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "behavior,code,attempts",
    [
        ("invalid_json", "MODEL_OUTPUT_INVALID", 2),
        ("provider_unavailable", "PROVIDER_UNAVAILABLE", 2),
        ("timeout", "MODEL_TIMEOUT", 1),
    ],
)
def test_gateway_failure_is_partial_with_real_scores(behavior, code, attempts):
    async def run():
        directory = FakeModelDirectory()
        gateway = FakeModelGateway(directory, failures={"diagnosis_report": behavior})
        app = create_app(Settings(_env_file=None), directory=directory, gateway=gateway)
        app.state.platform.reporting.timeout_seconds = 0.01
        async with clients(app) as (client,):
            _, _, body = await prepared(client)
            task, diagnosis = await diagnose(client, body)
            assert task["status"] == diagnosis["status"] == "partial"
            assert [i["score_result"]["score"] for i in diagnosis["items"]] == [66.7, 0]
            assert all(
                i["status"] == "score_only" and i["report"] is None and i["error"]["code"] == code
                for i in diagnosis["items"]
            )
            assert (
                await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            ).status_code == 200
            assert [c.attempts for c in gateway.calls] == [attempts, attempts]

    asyncio.run(run())


def test_one_scoring_failure_keeps_other_job():
    async def run():
        executor = FakeTaskExecutor()
        app = create_app(Settings(_env_file=None), executor=executor)
        async with clients(app) as (client,):
            _, jobs, body = await prepared(client)
            executor.failures[f"scoring:{jobs[1]['id']}"] = "INTERNAL_ERROR"
            task, diagnosis = await diagnose(client, body)
            assert task["status"] == "partial"
            assert [i["status"] for i in diagnosis["items"]] == ["succeeded", "failed"]
            executor.failures[f"scoring:{jobs[0]['id']}"] = "INTERNAL_ERROR"
            task, diagnosis = await diagnose(client, body)
            assert task["status"] == "failed" and task["error"]
            assert all(i["score_result"] is None for i in diagnosis["items"])

    asyncio.run(run())


def test_m5_model_errors_map_to_contract_before_enqueue_and_during_execution():
    async def run():
        directory = FakeModelDirectory()
        gate = asyncio.Event()
        executor = FakeTaskExecutor(gate=gate)
        app = create_app(Settings(_env_file=None), directory=directory, executor=executor)
        async with clients(app) as (client,):
            await session(client)
            check(
                await post(
                    client,
                    "/api/v1/jobs",
                    {
                        "raw_text": SYNTHETIC_JOB_RAW_TEXT,
                        "company_context": "",
                        "model_id": "missing",
                    },
                ),
                422,
                code="MODEL_UNAVAILABLE",
            )
            assert not app.state.platform.repo.tasks
            accepted = check(
                await post(
                    client,
                    "/api/v1/jobs",
                    {
                        "raw_text": SYNTHETIC_JOB_RAW_TEXT,
                        "company_context": "",
                        "model_id": "demo-model-b",
                    },
                ),
                202,
                "TaskAccepted",
            )
            await asyncio.wait_for(executor.started.wait(), 1)
            directory.disable("demo-model-b")
            gate.set()
            task, _ = await poll(client, accepted["task_id"])
            assert task["status"] == "failed" and task["error"]["code"] == "MODEL_UNAVAILABLE"
            assert not app.state.platform.repo.jobs

    asyncio.run(run())


def test_acceptance_two_distinct_extracted_jobs():
    """Two independently extracted and confirmed JDs must stay isolated through diagnosis."""

    async def run():
        app = create_app(Settings(_env_file=None))
        async with clients(app) as (client,):
            profile = await confirmed_profile(client)
            assert SECOND_JD != SYNTHETIC_JOB_RAW_TEXT
            contexts = ["合成数据开发背景，仅作补充。", "合成运维背景，仅作补充。"]
            first = await extracted_job(client, company_context=contexts[0])
            assert first["status"] == "succeeded"
            second = await extracted_job(client, SECOND_JD, company_context=contexts[1])
            assert second["status"] == "succeeded", second
            job = check(
                await client.get(f"/api/v1/jobs/{second['result']['resource_id']}"), 200, "Job"
            )
            assert all(r["quote"] in SECOND_JD for r in job["content"]["requirements"])
            assert any(r["target"] == "Kubernetes" for r in job["content"]["requirements"])
            jobs = []
            for task, raw_text, context in zip(
                (first, second), (SYNTHETIC_JOB_RAW_TEXT, SECOND_JD), contexts, strict=True
            ):
                jid = task["result"]["resource_id"]
                draft = check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job")
                assert draft["version"] == 1 and not draft["confirmed"]
                assert draft["raw_text"] == raw_text
                assert draft["content"]["company_context"] == context
                assert all(r["quote"] in raw_text for r in draft["content"]["requirements"])
                jobs.append(
                    check(
                        await client.post(
                            f"/api/v1/jobs/{jid}/confirm", json={"version": draft["version"]}
                        ),
                        200,
                        "Job",
                    )
                )
            assert jobs[0]["id"] != jobs[1]["id"]
            assert [r["target"] for r in jobs[1]["content"]["requirements"]] == ["Kubernetes"]
            models = check(await client.get("/api/v1/models"), 200, "ModelList")
            assert any(
                m["id"] == "demo-model-b" and "diagnosis_report" in m["capabilities"]
                for m in models["items"]
            )
            body = {
                "profile": {"id": profile["id"], "version": profile["version"]},
                "jobs": [{"id": j["id"], "version": j["version"]} for j in jobs],
                "model_id": "demo-model-b",
            }
            task, diagnosis = await diagnose(client, body)
            assert task["status"] == diagnosis["status"] == "succeeded"
            assert diagnosis["profile"] == body["profile"]
            assert [item["job"] for item in diagnosis["items"]] == body["jobs"]
            assert all(item["status"] == "succeeded" for item in diagnosis["items"])
            scores = [item["score_result"] for item in diagnosis["items"]]
            # The canonical golden case is from docs/05-scoring.md. Kubernetes
            # has no profile evidence, so its independent result is unknown/0.
            assert [score["score"] for score in scores] == [66.7, 0.0]
            assert [score["unknown_weight_ratio"] for score in scores] == [0.1667, 1.0]
            first_r1 = scores[0]["assessments"][0]
            second_r1 = scores[1]["assessments"][0]
            assert first_r1["requirement_id"] == second_r1["requirement_id"] == "r1"
            assert (first_r1["status"], first_r1["evidence_ids"]) == ("met", ["e1"])
            assert (second_r1["status"], second_r1["evidence_ids"]) == ("unknown", [])
            assert len(scores[1]["assessments"]) == 1
            for item, confirmed in zip(diagnosis["items"], jobs, strict=True):
                requirements = {r["id"] for r in confirmed["content"]["requirements"]}
                assert {g["requirement_id"] for g in item["report"]["gaps"]} <= requirements
                assert "演示数据" in item["report"]["summary"]
                assert item["model_metadata"]["provider"] == "fake"
                assert item["model_metadata"]["model_id"] == body["model_id"]
            gaps = diagnosis["items"][1]["report"]["gaps"]
            assert len(gaps) == 1
            assert gaps[0]["requirement_id"] == "r1"
            assert gaps[0]["kind"] == "needs_evidence" and gaps[0]["evidence_ids"] == []
            exported = await client.get(f"/api/v1/diagnoses/{diagnosis['id']}/export")
            assert exported.status_code == 200
            assert all(f"岗位 {j['id']} / v{j['version']}" in exported.text for j in jobs)
            assert "66.7" in exported.text and "coverage-v1" in exported.text
            assert "matcher-v1" in exported.text and "演示数据" in exported.text
            saved = copy.deepcopy(diagnosis)
            body["model_id"] = "demo-model-a"
            other_task, other = await diagnose(client, body)
            assert other_task["status"] == "succeeded"
            assert [item["score_result"] for item in other["items"]] == scores
            assert all(
                item["model_metadata"]["model_id"] == "demo-model-a" for item in other["items"]
            )
            assert (
                check(await client.get(f"/api/v1/diagnoses/{saved['id']}"), 200, "Diagnosis")
                == saved
            )

    asyncio.run(run())


def test_unknown_synthetic_input_fails_without_creating_or_replacing_a_job():
    async def run():
        app = create_app(Settings(_env_file=None))
        async with clients(app) as (client,):
            await session(client)
            known = await extracted_job(client)
            assert known["status"] == "succeeded"
            jid = known["result"]["resource_id"]
            saved = check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job")
            failed = await extracted_job(client, "不在合成目录中的虚构岗位。")
            assert failed["status"] == "failed" and failed["result"] is None
            assert failed["error"]["code"] and failed["error"]["message"]
            assert set(app.state.platform.repo.jobs) == {jid}
            assert check(await client.get(f"/api/v1/jobs/{jid}"), 200, "Job") == saved
            assert check(await client.get(f"/api/v1/tasks/{failed['id']}"), 200, "Task") == failed

    asyncio.run(run())
