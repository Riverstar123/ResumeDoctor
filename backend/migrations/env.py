"""Run migrations using the configured PostgreSQL connection, without logging it."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.platform.repositories.schema import metadata
from app.settings import load_settings


def database_url():
    value = (
        os.environ.get("RD_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or load_settings().database_url.get_secret_value()
    )
    if not value:
        raise RuntimeError("Set RD_DATABASE_URL or DATABASE_URL for PostgreSQL migrations")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://") :]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    if not value.startswith("postgresql+psycopg://"):
        raise RuntimeError("DB-01 migrations require PostgreSQL with psycopg")
    return value


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()
