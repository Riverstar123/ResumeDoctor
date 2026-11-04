"""Repository adapters; PostgreSQL dependencies are loaded only when selected."""

from app.platform.repositories.memory import (
    IdempotencyRecord,
    InMemoryRepository,
    Owned,
    SessionRecord,
    Versioned,
    new_id,
    timestamp,
)

__all__ = [
    "IdempotencyRecord",
    "InMemoryRepository",
    "Owned",
    "SessionRecord",
    "Versioned",
    "new_id",
    "timestamp",
    "PostgreSQLRepository",
    "SQLiteRepository",
    "database_repository",
]


def __getattr__(name):
    if name == "PostgreSQLRepository":
        from app.platform.repositories.postgres import PostgreSQLRepository

        return PostgreSQLRepository
    if name == "SQLiteRepository":
        from app.platform.repositories.sqlite import SQLiteRepository

        return SQLiteRepository
    raise AttributeError(name)


def database_repository(url):
    """Select the explicit persistent adapter; never fall back to memory."""
    if url.startswith(("sqlite:///", "sqlite+pysqlite:///")):
        from app.platform.repositories.sqlite import SQLiteRepository

        return SQLiteRepository(url)
    from app.platform.repositories.postgres import PostgreSQLRepository

    return PostgreSQLRepository(url)
