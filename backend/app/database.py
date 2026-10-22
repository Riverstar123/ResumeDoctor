"""Explicit PostgreSQL composition root and scheduled cleanup command.

Importing this module neither reads settings nor connects to a database.
Migrations are an explicit operator action; API startup never creates tables.
"""

import json

from app.llm import FakeModelDirectory
from app.main import create_app as create_platform_app
from app.platform.database_service import DatabasePlatform
from app.platform.integration import GatewayCatalog
from app.settings import Settings, load_settings


def create_app(settings: Settings | None = None, *, repository=None, catalog=None):
    settings = settings if settings is not None else load_settings()
    if settings.llm_mode != "fake":
        raise ValueError(
            "Database assembly requires LLM_MODE=fake; real integration belongs to INT-02"
        )
    if repository is None:
        # Keep database extras optional for the existing fake-only factories.
        from app.platform.repositories import PostgreSQLRepository

        repository = PostgreSQLRepository(settings.database_url.get_secret_value())
    platform = DatabasePlatform(
        repository,
        catalog if catalog is not None else GatewayCatalog(FakeModelDirectory()),
        settings.upload_dir,
    )
    app = create_platform_app(settings, platform=platform)
    app.title = "ResumeDoctor DB-01 / PostgreSQL persistence, queued tasks"
    return app


def cleanup() -> None:
    """Run periodically; output only aggregate counts, never session/file data."""
    from app.platform.repositories import PostgreSQLRepository

    settings = load_settings()
    repository = PostgreSQLRepository(settings.database_url.get_secret_value())
    try:
        result = repository.cleanup_expired()
        files_removed = repository.retry_file_cleanup(settings.upload_dir)
        if isinstance(result, dict):
            counts = {k: v for k, v in result.items() if isinstance(v, int)}
            counts["files_removed"] = files_removed
            print(json.dumps(counts))
        else:
            print(json.dumps({"sessions_removed": result, "files_removed": files_removed}))
    finally:
        repository.close()


if __name__ == "__main__":
    cleanup()
