"""Add separately persisted optional advice without rewriting historical reports."""

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_diagnosis_items_owner", "diagnosis_items", ["session_id", "id"])
    op.create_table(
        "enhancements",
        Column("id", UUID(as_uuid=False), primary_key=True),
        Column("session_id", UUID(as_uuid=False), nullable=False),
        Column("diagnosis_id", UUID(as_uuid=False), nullable=False),
        Column("item_id", UUID(as_uuid=False), nullable=False),
        Column("task_id", UUID(as_uuid=False), nullable=False, unique=True),
        Column("cache_key", Text, nullable=False),
        Column("ordinal", Integer, nullable=False),
        Column("requirement_ids", JSONB, nullable=False),
        Column("report", JSONB(none_as_null=True)),
        Column("model_metadata", JSONB(none_as_null=True)),
        Column("created_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["session_id", "item_id"],
            ["diagnosis_items.session_id", "diagnosis_items.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["session_id", "task_id"],
            ["tasks.session_id", "tasks.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("session_id", "cache_key"),
        UniqueConstraint("item_id", "ordinal"),
    )
    op.create_index("ix_enhancements_item", "enhancements", ["session_id", "item_id", "created_at"])


def downgrade():
    op.drop_table("enhancements")
    op.drop_constraint("uq_diagnosis_items_owner", "diagnosis_items", type_="unique")
