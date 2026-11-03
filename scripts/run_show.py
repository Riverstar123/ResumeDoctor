"""Start the display API and a supervised worker; never try to prevent platform sleep."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.llm.config import build_llm
    from app.platform.repositories.sqlite import initialize_sqlite
    from app.show import show_settings

    os.umask(0o077)
    settings = show_settings()
    # Validate model configuration before spawning processes. No provider call here.
    build_llm(settings)
    settings.upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    initialize_sqlite(settings.database_url.get_secret_value())
    env = dict(os.environ)
    env.update(
        DATABASE_URL=settings.database_url.get_secret_value(),
        UPLOAD_DIR=str(settings.upload_dir),
        ALLOWED_ORIGINS=json.dumps(settings.allowed_origins),
        LLM_MODE=settings.llm_mode,
        LLM_PROVIDER=settings.llm_provider,
        LLM_MODEL_A="",
        LLM_MODEL_B="",
        LLM_BASE_URL_B="",
        LLM_API_KEY_B="",
        PYTHONPATH=str(ROOT / "backend"),
    )
    commands = [
        [sys.executable, "-m", "app.platform.jobs"],
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.show:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            str(int(os.environ.get("PORT", "8000"))),
            "--no-access-log",
        ],
    ]
    stopped = False
    children = []

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env))
        while not stopped:
            if any(child.poll() is not None for child in children):
                # Fail together: an alive API with a dead worker is not a usable app.
                return 1
            time.sleep(0.25)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
