"""File-backed SQLite fallback for a small, single-host demonstration.

BEGIN IMMEDIATE serializes short transactions across threads and processes.
This replaces PostgreSQL row locks, including queue claim and lease fencing;
silently ignoring FOR UPDATE without this boundary would be unsafe.
"""

import argparse
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import make_url

from .schema import metadata
from .sql import SQLRepository

SCHEMA_VERSION = 1


def sqlite_engine(url):
    parsed = make_url(url)
    if (
        parsed.drivername not in {"sqlite", "sqlite+pysqlite"}
        or not parsed.database
        or parsed.database == ":memory:"
        or parsed.database.startswith("file:")
        or parsed.query
    ):
        raise ValueError("SQLite requires a local database file without URI/query options")
    path = Path(parsed.database).resolve()
    if not path.parent.is_dir():
        raise ValueError("Create the SQLite data directory before initialization")
    engine = create_engine(
        parsed.set(database=str(path)),
        hide_parameters=True,
        connect_args={"check_same_thread": False, "timeout": 10},
        # The HTTP I/O limiter bounds whole operations (also filesystem work);
        # this smaller pool bounds actual DB connections. Excess I/O waits for
        # a checkout, and SQLite still admits only one BEGIN IMMEDIATE at a time.
        pool_size=4,
        max_overflow=0,
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def initialize_sqlite(url):
    """Explicit, idempotent provisioning; never overwrite an unknown schema."""
    engine = sqlite_engine(url)
    try:
        # WAL configuration must happen outside the explicit transaction hook.
        raw = engine.raw_connection()
        try:
            mode = raw.cursor().execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise ValueError("SQLite WAL mode is required")
        finally:
            raw.close()
        with engine.begin() as connection:
            version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version == SCHEMA_VERSION:
                return
            if version != 0 or inspect(connection).get_table_names():
                raise ValueError(
                    "Unsupported SQLite schema; preserve the file and migrate explicitly"
                )
            metadata.create_all(connection)
            for name in ("profile_versions", "job_versions"):
                table = metadata.tables[name]
                unchanged = " AND ".join(
                    f'NEW."{column.name}" IS OLD."{column.name}"'
                    for column in table.columns
                    if column.name != "confirmed_at"
                )
                connection.exec_driver_sql(
                    f'CREATE TRIGGER protect_{name} BEFORE UPDATE ON "{name}" '
                    f"WHEN NOT ({unchanged}) OR "
                    "(OLD.confirmed_at IS NOT NULL AND NEW.confirmed_at IS NOT OLD.confirmed_at) "
                    "BEGIN SELECT RAISE(ABORT, 'Resource versions are immutable'); END"
                )
            connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
    finally:
        engine.dispose()


class SQLiteRepository(SQLRepository):
    def __init__(self, url, clock=None):
        engine = sqlite_engine(url)
        try:
            with engine.connect() as connection:
                if connection.exec_driver_sql("PRAGMA user_version").scalar_one() != SCHEMA_VERSION:
                    raise ValueError("Initialize the SQLite database explicitly before starting")
        except BaseException:
            engine.dispose()
            raise
        super().__init__(engine, clock)

    def upsert(self, table):
        return insert(table)


def main():
    from app.settings import load_settings

    argparse.ArgumentParser(description="Initialize the SQLite fallback database").parse_args()
    initialize_sqlite(load_settings().database_url.get_secret_value())


if __name__ == "__main__":
    main()
