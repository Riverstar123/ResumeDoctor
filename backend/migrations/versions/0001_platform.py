"""Initial PostgreSQL platform schema with immutable resource versions.

Revision ID: 0001
Revises: None
"""

from alembic import op
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def uuid(name, **kwargs):
    return Column(name, UUID(as_uuid=False), **kwargs)


def time(name, **kwargs):
    return Column(name, DateTime(timezone=True), **kwargs)


def session_fk():
    return ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE")


def owned_unique():
    return UniqueConstraint("session_id", "id")


def task_fk(column):
    return ForeignKeyConstraint(
        ["session_id", column],
        ["tasks.session_id", "tasks.id"],
        deferrable=True,
        initially="DEFERRED",
    )


def upgrade():
    op.create_table(
        "sessions",
        uuid("id", primary_key=True),
        Column("token_hash", Text, nullable=False, unique=True),
        Column("consent_version", Text, nullable=False),
        time("expires_at", nullable=False),
        time("revoked_at"),
        time("created_at", nullable=False),
    )
    op.create_table(
        "tasks",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        Column("kind", Text, nullable=False),
        Column("status", Text, nullable=False),
        Column("input", JSONB, nullable=False),
        Column("result", JSONB(none_as_null=True)),
        Column("error", JSONB(none_as_null=True)),
        Column("model_id", Text, nullable=False),
        Column("model_snapshot", JSONB, nullable=False),
        Column("attempt", Integer, nullable=False),
        uuid("lease_token"),
        time("lease_until"),
        time("heartbeat_at"),
        time("deadline_at", nullable=False),
        time("created_at", nullable=False),
        time("updated_at", nullable=False),
        session_fk(),
        owned_unique(),
        CheckConstraint(
            "kind IN ('document_parse','profile_chat','job_parse','diagnosis')",
            name="ck_tasks_kind",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','partial','failed')", name="ck_tasks_status"
        ),
        CheckConstraint("attempt >= 0", name="ck_tasks_attempt"),
    )
    op.create_table(
        "profiles",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        Column("latest_version", Integer, nullable=False),
        time("created_at", nullable=False),
        session_fk(),
        owned_unique(),
        CheckConstraint("latest_version >= 1", name="ck_profiles_latest_version"),
    )
    op.create_table(
        "profile_versions",
        uuid("profile_id", primary_key=True),
        uuid("session_id", nullable=False),
        Column("version", Integer, primary_key=True),
        Column("content", JSONB, nullable=False),
        time("confirmed_at"),
        uuid("created_by_task_id", unique=True),
        time("created_at", nullable=False),
        session_fk(),
        UniqueConstraint("session_id", "profile_id", "version"),
        ForeignKeyConstraint(
            ["session_id", "profile_id"], ["profiles.session_id", "profiles.id"], ondelete="CASCADE"
        ),
        task_fk("created_by_task_id"),
        CheckConstraint("version >= 1", name="ck_profile_versions_version"),
    )
    op.create_table(
        "jobs",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        Column("latest_version", Integer, nullable=False),
        time("created_at", nullable=False),
        session_fk(),
        owned_unique(),
        CheckConstraint("latest_version >= 1", name="ck_jobs_latest_version"),
    )
    op.create_table(
        "job_versions",
        uuid("job_id", primary_key=True),
        uuid("session_id", nullable=False),
        Column("version", Integer, primary_key=True),
        Column("raw_text", Text, nullable=False),
        Column("content", JSONB, nullable=False),
        time("confirmed_at"),
        uuid("created_by_task_id", unique=True),
        time("created_at", nullable=False),
        session_fk(),
        UniqueConstraint("session_id", "job_id", "version"),
        ForeignKeyConstraint(
            ["session_id", "job_id"], ["jobs.session_id", "jobs.id"], ondelete="CASCADE"
        ),
        task_fk("created_by_task_id"),
        CheckConstraint("version >= 1", name="ck_job_versions_version"),
    )
    op.create_table(
        "documents",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        uuid("profile_id"),
        Column("storage_key", Text),
        Column("original_name", Text, nullable=False),
        Column("media_type", Text, nullable=False),
        Column("size_bytes", BigInteger, nullable=False),
        Column("status", Text, nullable=False),
        time("deleted_at"),
        time("created_at", nullable=False),
        session_fk(),
        owned_unique(),
        ForeignKeyConstraint(
            ["session_id", "profile_id"], ["profiles.session_id", "profiles.id"], ondelete="CASCADE"
        ),
        CheckConstraint("size_bytes >= 0 AND size_bytes <= 10485760", name="ck_documents_size"),
        CheckConstraint(
            "status IN ('stored','processing','parsed','failed','deleted')",
            name="ck_documents_status",
        ),
    )
    op.create_table(
        "messages",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        uuid("profile_id", nullable=False),
        uuid("task_id", nullable=False),
        Column("role", Text, nullable=False),
        Column("content", Text, nullable=False),
        time("created_at", nullable=False),
        session_fk(),
        owned_unique(),
        ForeignKeyConstraint(
            ["session_id", "profile_id"], ["profiles.session_id", "profiles.id"], ondelete="CASCADE"
        ),
        task_fk("task_id"),
        UniqueConstraint("task_id", "role"),
        CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
    )
    op.create_table(
        "diagnoses",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        uuid("task_id", nullable=False, unique=True),
        uuid("profile_id", nullable=False),
        Column("profile_version", Integer, nullable=False),
        Column("model_id", Text, nullable=False),
        time("created_at", nullable=False),
        session_fk(),
        owned_unique(),
        task_fk("task_id"),
        ForeignKeyConstraint(
            ["session_id", "profile_id", "profile_version"],
            [
                "profile_versions.session_id",
                "profile_versions.profile_id",
                "profile_versions.version",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_table(
        "diagnosis_items",
        uuid("id", primary_key=True),
        uuid("session_id", nullable=False),
        uuid("diagnosis_id", nullable=False),
        uuid("job_id", nullable=False),
        Column("job_version", Integer, nullable=False),
        Column("status", Text, nullable=False),
        Column("score_result", JSONB(none_as_null=True)),
        Column("report", JSONB(none_as_null=True)),
        Column("error", JSONB(none_as_null=True)),
        Column("model_metadata", JSONB(none_as_null=True)),
        time("created_at", nullable=False),
        time("updated_at", nullable=False),
        session_fk(),
        owned_unique(),
        ForeignKeyConstraint(
            ["session_id", "diagnosis_id"],
            ["diagnoses.session_id", "diagnoses.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["session_id", "job_id", "job_version"],
            ["job_versions.session_id", "job_versions.job_id", "job_versions.version"],
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("diagnosis_id", "job_id", "job_version"),
        CheckConstraint(
            "status IN ('pending','scoring','reporting','succeeded','score_only','failed')",
            name="ck_diagnosis_items_status",
        ),
    )
    op.create_table(
        "idempotency_keys",
        uuid("session_id", primary_key=True),
        Column("key", Text, primary_key=True),
        Column("operation", Text, nullable=False),
        Column("request_hash", Text, nullable=False),
        Column("resource_type", Text, nullable=False),
        uuid("resource_id", nullable=False),
        time("created_at", nullable=False),
        session_fk(),
    )
    op.create_table(
        "file_cleanup",
        Column("storage_key", Text, primary_key=True),
        time("created_at", nullable=False),
        Column("attempt", Integer, nullable=False),
        time("next_attempt_at", nullable=False),
        CheckConstraint("attempt >= 0", name="ck_file_cleanup_attempt"),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index(
        "ix_tasks_status_lease_until_created_at", "tasks", ["status", "lease_until", "created_at"]
    )
    op.create_index("ix_messages_profile_id_created_at", "messages", ["profile_id", "created_at"])
    op.create_index("ix_diagnosis_items_diagnosis_id", "diagnosis_items", ["diagnosis_id"])
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])
    op.create_index("ix_file_cleanup_next_attempt_at", "file_cleanup", ["next_attempt_at"])
    op.create_foreign_key(
        "fk_profiles_latest_version",
        "profiles",
        "profile_versions",
        ["session_id", "id", "latest_version"],
        ["session_id", "profile_id", "version"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_jobs_latest_version",
        "jobs",
        "job_versions",
        ["session_id", "id", "latest_version"],
        ["session_id", "job_id", "version"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute("""
        CREATE FUNCTION protect_resource_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(NEW) - 'confirmed_at') IS DISTINCT FROM
               (to_jsonb(OLD) - 'confirmed_at') THEN
                RAISE EXCEPTION 'Resource version contents are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.confirmed_at IS NOT NULL AND
               NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at THEN
                RAISE EXCEPTION 'Resource confirmation cannot be changed'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    for table_name in ("profile_versions", "job_versions"):
        op.execute(
            f"CREATE TRIGGER protect_{table_name} BEFORE UPDATE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION protect_resource_version()"
        )


def downgrade():
    op.drop_constraint("fk_profiles_latest_version", "profiles", type_="foreignkey")
    op.drop_constraint("fk_jobs_latest_version", "jobs", type_="foreignkey")
    op.drop_table("file_cleanup")
    op.drop_table("idempotency_keys")
    op.drop_table("diagnosis_items")
    op.drop_table("diagnoses")
    op.drop_table("messages")
    op.drop_table("documents")
    op.drop_table("job_versions")
    op.drop_table("jobs")
    op.drop_table("profile_versions")
    op.drop_table("profiles")
    op.drop_table("tasks")
    op.drop_table("sessions")
    op.execute("DROP FUNCTION protect_resource_version()")
