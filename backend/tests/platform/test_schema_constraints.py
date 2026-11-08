"""Check the PostgreSQL DDL even when no live PostgreSQL server is configured."""

# ruff: noqa: E402 -- database dependencies remain optional.
import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.platform.repositories import schema


def test_diagnosis_item_owner_constraint_is_emitted_once():
    ddl = str(CreateTable(schema.diagnosis_items).compile(dialect=postgresql.dialect()))
    assert ddl.count("CONSTRAINT uq_diagnosis_items_session_id UNIQUE (session_id, id)") == 1
    names = [c.name for c in schema.diagnosis_items.constraints if c.name is not None]
    assert len(names) == len(set(names))
