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
]


def __getattr__(name):
    if name == "PostgreSQLRepository":
        from app.platform.repositories.postgres import PostgreSQLRepository

        return PostgreSQLRepository
    raise AttributeError(name)
