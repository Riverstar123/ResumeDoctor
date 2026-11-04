"""Same-origin built frontend and persistent API for the class display server."""

import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import URL

from app.database import create_app as database_app
from app.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def show_settings():
    """Ignore workstation .env files; the display deployment uses DeepSeek only."""
    directory = Path(os.environ.get("DATA_DIR", "/data"))
    if not directory.is_absolute():
        raise ValueError("DATA_DIR must be an absolute persistent directory")
    mode = os.environ.get("LLM_MODE", "real")
    return Settings(
        _env_file=None,
        database_url=URL.create(
            "sqlite", database=(directory / "resumedoctor.sqlite3").as_posix()
        ).render_as_string(hide_password=False),
        upload_dir=directory / "uploads",
        allowed_origins=[os.environ.get("SHOW_ORIGIN", "https://mf18.show.lingnan.top")],
        session_cookie_secure=os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true",
        llm_mode=mode,
        llm_provider="openai_compatible" if mode == "real" else "fake",
        llm_model_a="",
        llm_model_b="",
        llm_base_url_b="",
        llm_api_key_b="",
    )


def create_app(settings=None, *, dist=None, **ports):
    settings = settings if settings is not None else show_settings()
    root = (Path(dist) if dist is not None else PROJECT_ROOT / "frontend" / "dist").resolve()
    if not (root / "index.html").is_file() or not (root / "assets").is_dir():
        raise ValueError("Build the HTTP frontend before starting the display application")
    app = database_app(settings, documentation_enabled=False, **ports)
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        # Serve only Vite's public build; never expose backend, uploads or DATA_DIR.
        target = (root / path).resolve()
        if not target.is_relative_to(root) or path.split("/", 1)[0] in {
            "api",
            "healthz",
            "docs",
            "redoc",
            "openapi.json",
        }:
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        if "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(404)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
