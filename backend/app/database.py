"""Explicit PostgreSQL composition root and scheduled cleanup command.

Importing this module neither reads settings nor connects to a database.
Migrations are an explicit operator action; API startup never creates tables.
"""

import json

from app.main import create_app as create_platform_app
from app.platform.database_service import DatabasePlatform
from app.runtime import business_modules
from app.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None, *, repository=None, catalog=None, directory=None, gateway=None
):
    settings = settings if settings is not None else load_settings()
    modules = business_modules(settings, directory=directory, gateway=gateway)
    if repository is None:
        # Keep database extras optional for the existing fake-only factories.
        from app.platform.repositories import PostgreSQLRepository

        repository = PostgreSQLRepository(settings.database_url.get_secret_value())
    platform = DatabasePlatform(
        repository,
        catalog if catalog is not None else modules.catalog,
        settings.upload_dir,
        reporting=modules.reporting,
    )
    app = create_platform_app(settings, platform=platform)
    app.state.gateway = modules.gateway
    app.title = "ResumeDoctor INT-02 / PostgreSQL, business modules, fake model"
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
