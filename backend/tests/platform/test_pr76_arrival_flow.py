"""Real DOCX parser + SQLite + native response replay through report/export."""

# ruff: noqa: F811 -- reusable SQLite fixtures.
import asyncio
import copy
import io
import json
import zipfile
from xml.sax.saxutils import escape

import httpx
import pytest

from app.database import create_app
from app.llm import build_llm
from app.platform.jobs.worker import create_worker
from tests.intake.test_pr76_context_review import arrival_job, arrival_profile
from tests.llm.test_real_gateway import real_settings
from tests.llm.test_structured_output import tool_result

from .test_api import check, post, session
from .test_int02 import client_for, docx_bytes
from .test_sqlite import repo, url  # noqa: F401

HISTORICAL_ARRIVAL = "历史到岗安排（已于2026-10结束）：“可立即到岗，但需要四周通知期”"
CURRENT_NOTICE = "2026年11月目前仍需四周通知期"
MIXED_ARRIVAL = f"历史到岗安排（已于2026-10结束）：“当时需四周通知期，但{CURRENT_NOTICE}”"


@pytest.mark.parametrize("cross_source", [False, True])
@pytest.mark.parametrize(
    "quote,end_month",
    [
        ("目前不能保证可以立即到岗", None),
        ("可立即到岗，但入职需等待四周", None),
        ("可立即到岗，但需要四周通知期", None),
        ("可立即到岗，但录用后四周才能开始工作", None),
        ("2026年10月上份实习结束，目前可立即到岗，但需要四周通知期", "2026-10"),
        (HISTORICAL_ARRIVAL, "2026-10"),
        (MIXED_ARRIVAL, "2026-10"),
    ],
)
def test_uncertain_upload_needs_no_repair_and_base_survives_enhancement_failure(
    repo, url, tmp_path, quote, end_month, cross_source
):
    counts = {"extract": 0, "enhancement": 0}

    async def response(request):
        body = json.loads(request.content)
        sent, _ = json.JSONDecoder().raw_decode(
            body["messages"][1]["content"].split("任务数据（JSON）：\n", 1)[1]
        )
        if "source_text" in sent:
            counts["extract"] += 1
            assert quote in sent["source_text"]  # Came through the actual DOCX parser.
            p = arrival_profile(quote)
            p.facts[0].end_month = end_month
            if quote == MIXED_ARRIVAL:
                p.facts[0].attributes[0].quote = CURRENT_NOTICE
            p.evidence[0].source_type = sent["source_type"]
            p.evidence[0].source_id = sent["source_id"]
            # Even if called again, this supplier NEVER repairs the interpretation.
            return tool_result(p.model_dump(mode="json"))
        if "raw_text" in sent:
            return tool_result(arrival_job().model_dump(mode="json"))
        counts["enhancement"] += 1
        return tool_result({"choices": "invalid synthetic response"})

    settings = real_settings(
        llm_model="deepseek-flash",
        llm_base_url="https://api.deepseek.com",
        database_url=url,
        upload_dir=tmp_path / "uploads",
    )
    llm = build_llm(settings, transport=httpx.MockTransport(response))
    app = create_app(settings, repository=repo, gateway=llm.gateway, directory=llm.directory)
    worker = create_worker(settings, repository=repo, gateway=llm.gateway, directory=llm.directory)
    file = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(docx_bytes())) as template,
        zipfile.ZipFile(file, "w") as output,
    ):
        for name in template.namelist():
            output.writestr(
                name,
                (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    f"<w:body><w:p><w:r><w:t>{escape(quote)}</w:t></w:r></w:p></w:body></w:document>"
                )
                if name == "word/document.xml"
                else template.read(name),
            )

    async def run():
        async with client_for(app) as client:
            await session(client)
            accepted = check(
                await client.post(
                    "/api/v1/documents",
                    files={
                        "file": (
                            "synthetic.docx",
                            file.getvalue(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                    },
                    data={"model_id": "real-default"},
                    headers={"Idempotency-Key": "pr76-arrival-upload-test"},
                ),
                202,
                "TaskAccepted",
            )
            assert await worker.run_once()
            task = check(await client.get(f"/api/v1/tasks/{accepted['task_id']}"), 200, "Task")
            assert task["status"] == "succeeded", task
            assert counts["extract"] == 1
            path = f"/api/v1/profiles/{task['result']['resource_id']}"
            p = check(await client.get(path), 200, "Profile")
            assert not p["content"]["facts"][0]["attributes"]
            assert p["content"]["facts"][0]["end_month"] == end_month
            assert p["content"]["facts"][0]["unverified_attributes"][0]["value"] == "immediate"
            assert p["content"]["evidence"][0]["quote"] == quote
            if cross_source:
                # Keep the uploaded candidate and add a separate manual source.
                # Saving/confirming the whole profile must not erase the conflict.
                added = arrival_profile("可以立即到岗").model_dump(mode="json")
                added["facts"][0]["id"] = "f2"
                added["facts"][0]["evidence_ids"] = ["e2"]
                added["evidence"][0]["id"] = "e2"
                content = {
                    **p["content"],
                    "facts": [*p["content"]["facts"], *added["facts"]],
                    "evidence": [*p["content"]["evidence"], *added["evidence"]],
                }
                p = check(
                    await client.put(path, json={"base_version": p["version"], "content": content}),
                    200,
                    "Profile",
                )
            confirmed = check(
                await client.post(path + "/confirm", json={"version": p["version"]}), 200, "Profile"
            )
            assert (
                confirmed["content"] == p["content"]
            )  # Confirmation does not promote a candidate.

            accepted = check(
                await post(
                    client,
                    "/api/v1/jobs",
                    {"raw_text": "立即到岗", "company_context": "", "model_id": "real-default"},
                ),
                202,
                "TaskAccepted",
            )
            assert await worker.run_once()
            task = check(await client.get(f"/api/v1/tasks/{accepted['task_id']}"), 200, "Task")
            assert task["status"] == "succeeded", task
            jpath = f"/api/v1/jobs/{task['result']['resource_id']}"
            j = check(await client.get(jpath), 200, "Job")
            check(await client.post(jpath + "/confirm", json={"version": j["version"]}), 200, "Job")
            accepted = check(
                await post(
                    client,
                    "/api/v1/diagnoses",
                    {
                        "profile": {"id": p["id"], "version": p["version"]},
                        "jobs": [{"id": j["id"], "version": j["version"]}],
                        "model_id": None,
                    },
                ),
                202,
                "DiagnosisAccepted",
            )
            assert await worker.run_once()
            path = f"/api/v1/diagnoses/{accepted['diagnosis_id']}"
            base = check(await client.get(path), 200, "Diagnosis")
            assert base["status"] == "succeeded"
            item = base["items"][0]
            score = item["score_result"]
            assert score["assessments"][0]["status"] == "unknown" and score["score"] == 0
            if cross_source:
                assessment = score["assessments"][0]
                assert assessment["unknown_reason"] == "conflicting_evidence"
                assert assessment["evidence_ids"] == ["e1", "e2"]
                assert assessment["counted_in_score"] and score["unknown_weight_ratio"] == 1
            assert item["report"] is not None and counts["enhancement"] == 0
            endpoint = path + f"/items/{item['id']}/enhancements"
            accepted = check(
                await post(client, endpoint, {"model_id": "real-default"}), 202, "TaskAccepted"
            )
            assert await worker.run_once()
            task = check(await client.get(f"/api/v1/tasks/{accepted['task_id']}"), 200, "Task")
            assert task["status"] == "failed" and counts["enhancement"] == 2
            current = check(await client.get(path), 200, "Diagnosis")
            assert current["status"] == "succeeded"
            assert current["items"][0]["score_result"] == score
            assert current["items"][0]["report"] == item["report"]
            replay = check(
                await post(client, endpoint, {"model_id": "real-default"}), 202, "TaskAccepted"
            )
            assert replay["task_id"] == accepted["task_id"] and counts["enhancement"] == 2
            export = await client.get(path + "/export")
            assert export.status_code == 200 and item["report"]["summary"] in export.text
            stored_profile = check(
                await client.get(f"/api/v1/profiles/{p['id']}?version={p['version']}"),
                200,
                "Profile",
            )
            assert stored_profile["content"] == confirmed["content"]
            if cross_source and quote == HISTORICAL_ARRIVAL:
                # The existing remove-candidate action saves a new version. It
                # leaves source quotes and the earlier diagnosis untouched.
                edited = copy.deepcopy(stored_profile["content"])
                edited["facts"][0]["unverified_attributes"] = []
                ppath = f"/api/v1/profiles/{p['id']}"
                revised = check(
                    await client.put(ppath, json={"base_version": p["version"], "content": edited}),
                    200,
                    "Profile",
                )
                assert revised["version"] == p["version"] + 1
                check(
                    await client.post(ppath + "/confirm", json={"version": revised["version"]}),
                    200,
                    "Profile",
                )
                next_task = check(
                    await post(
                        client,
                        "/api/v1/diagnoses",
                        {
                            "profile": {"id": p["id"], "version": revised["version"]},
                            "jobs": [{"id": j["id"], "version": j["version"]}],
                            "model_id": None,
                        },
                    ),
                    202,
                    "DiagnosisAccepted",
                )
                assert await worker.run_once()
                next_path = f"/api/v1/diagnoses/{next_task['diagnosis_id']}"
                next_report = check(await client.get(next_path), 200, "Diagnosis")
                assert next_report["status"] == "succeeded"
                next_score = next_report["items"][0]["score_result"]
                assert next_score["score"] == 100
                assert next_score["assessments"][0]["evidence_ids"] == ["e2"]
                assert (await client.get(next_path + "/export")).status_code == 200
                old = check(await client.get(path), 200, "Diagnosis")
                assert old["items"][0]["score_result"] == score
                assert old["items"][0]["report"] == item["report"]
                assert edited["evidence"] == confirmed["content"]["evidence"]
                historical = check(
                    await client.get(ppath + f"?version={p['version']}"), 200, "Profile"
                )
                assert historical["content"] == confirmed["content"]
                assert counts == {"extract": 1, "enhancement": 2}

    asyncio.run(run())
