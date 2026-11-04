"""Exercise an unpacked release with runtime dependencies only, never an installed app."""

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--media-type", required=True)
    parser.add_argument("--expected-status", choices=["succeeded", "failed"], required=True)
    parser.add_argument("--dependency-dir", action="append", default=[])
    args = parser.parse_args()
    root = args.release.resolve()
    assert sys.flags.isolated and sys.flags.utf8_mode
    assert importlib.util.find_spec("app") is None, "Use a fresh venv without an installed project"
    sys.path.extend(args.dependency_dir)
    sys.path.insert(0, str(root / "backend"))

    import httpx

    from app.platform.repositories.sqlite import initialize_sqlite
    from app.show import create_app, show_settings

    settings = show_settings()
    settings.upload_dir.mkdir(parents=True)
    initialize_sqlite(settings.database_url.get_secret_value())
    app = create_app()
    env = dict(os.environ)
    env.update(
        PYTHONPATH=os.pathsep.join([str(root / "backend"), *args.dependency_dir]),
        DATABASE_URL=settings.database_url.get_secret_value(),
        UPLOAD_DIR=str(settings.upload_dir),
        ALLOWED_ORIGINS=json.dumps(settings.allowed_origins),
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=settings.allowed_origins[0],
            headers={"Origin": settings.allowed_origins[0]},
        ) as client:
            assert (await client.get("/")).status_code == 200
            created = await client.post("/api/v1/session", json={"consent_version": "v1"})
            assert created.status_code == 200, created.text
            response = await client.post(
                "/api/v1/documents",
                files={"file": (args.document.name, args.document.read_bytes(), args.media_type)},
                data={"model_id": "demo-model-a"},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert response.status_code == 202, response.text
            task_id = response.json()["task_id"]
            completed = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-X", "utf8", "-m", "app.platform.jobs", "--once"],
                cwd=root,
                env=env,
                capture_output=True,
                timeout=30,
            )
            assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
            task = (await client.get(f"/api/v1/tasks/{task_id}")).json()
            assert task["status"] == args.expected_status, task
            if args.expected_status == "succeeded":
                profile = await client.get(f"/api/v1/profiles/{task['result']['resource_id']}")
                assert profile.status_code == 200, profile.text
                content = profile.json()["content"]
                assert len(content["facts"]) == 3
                assert content["evidence"]
                assert all(
                    e["source_type"] == "document" and e["locator"] for e in content["evidence"]
                )
            else:
                assert task["error"]["code"] == "DOCUMENT_PARSE_FAILED", task
                assert task["result"] is None
            with app.state.platform.repo.engine.connect() as connection:
                from sqlalchemy import func, select

                from app.platform.repositories import schema

                assert connection.scalar(select(func.count()).select_from(schema.profiles)) == (
                    1 if args.expected_status == "succeeded" else 0
                )
            print(json.dumps({"document": args.document.name, "status": task["status"]}))
        await app.state.platform.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
