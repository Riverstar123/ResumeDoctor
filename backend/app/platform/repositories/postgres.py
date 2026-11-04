"""PostgreSQL adapter: row locks and native ON CONFLICT transactions."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects.postgresql import insert

from .sql import SQLRepository


class PostgreSQLRepository(SQLRepository):
    def __init__(self, engine: Engine | str, clock=None):
        if isinstance(engine, str):
            if engine.startswith("postgresql://"):
                engine = "postgresql+psycopg://" + engine[len("postgresql://") :]
            if not engine.startswith("postgresql+psycopg://"):
                raise ValueError("PostgreSQL with psycopg is required")
            engine = create_engine(engine, hide_parameters=True, pool_pre_ping=True)
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL is required")
        super().__init__(engine, clock)

    def upsert(self, table):
        return insert(table)
