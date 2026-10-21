"""PostgreSQL ownership and immutable resource-version schema (DB-01)."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


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


sessions = Table(
    "sessions",
    metadata,
    uuid("id", primary_key=True),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("consent_version", Text, nullable=False),
    time("expires_at", nullable=False),
    time("revoked_at"),
    time("created_at", nullable=False),
    Index("ix_sessions_expires_at", "expires_at"),
)

tasks = Table(
    "tasks",
    metadata,
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
        "status IN ('queued','running','succeeded','partial','failed')",
        name="ck_tasks_status",
    ),
    CheckConstraint("attempt >= 0", name="ck_tasks_attempt"),
    Index("ix_tasks_status_lease_until_created_at", "status", "lease_until", "created_at"),
)

profiles = Table(
    "profiles",
    metadata,
    uuid("id", primary_key=True),
    uuid("session_id", nullable=False),
    Column("latest_version", Integer, nullable=False),
    time("created_at", nullable=False),
    session_fk(),
    owned_unique(),
    CheckConstraint("latest_version >= 1", name="ck_profiles_latest_version"),
    ForeignKeyConstraint(
        ["session_id", "id", "latest_version"],
        ["profile_versions.session_id", "profile_versions.profile_id", "profile_versions.version"],
        name="fk_profiles_latest_version",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    ),
)

profile_versions = Table(
    "profile_versions",
    metadata,
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
        ["session_id", "profile_id"],
        ["profiles.session_id", "profiles.id"],
        ondelete="CASCADE",
    ),
    task_fk("created_by_task_id"),
    CheckConstraint("version >= 1", name="ck_profile_versions_version"),
)

jobs = Table(
    "jobs",
    metadata,
    uuid("id", primary_key=True),
    uuid("session_id", nullable=False),
    Column("latest_version", Integer, nullable=False),
    time("created_at", nullable=False),
    session_fk(),
    owned_unique(),
    CheckConstraint("latest_version >= 1", name="ck_jobs_latest_version"),
    ForeignKeyConstraint(
        ["session_id", "id", "latest_version"],
        ["job_versions.session_id", "job_versions.job_id", "job_versions.version"],
        name="fk_jobs_latest_version",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    ),
)

job_versions = Table(
    "job_versions",
    metadata,
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
        ["session_id", "job_id"],
        ["jobs.session_id", "jobs.id"],
        ondelete="CASCADE",
    ),
    task_fk("created_by_task_id"),
    CheckConstraint("version >= 1", name="ck_job_versions_version"),
)

documents = Table(
    "documents",
    metadata,
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
        ["session_id", "profile_id"],
        ["profiles.session_id", "profiles.id"],
        ondelete="CASCADE",
    ),
    CheckConstraint("size_bytes >= 0 AND size_bytes <= 10485760", name="ck_documents_size"),
    CheckConstraint(
        "status IN ('stored','processing','parsed','failed','deleted')",
        name="ck_documents_status",
    ),
)

messages = Table(
    "messages",
    metadata,
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
        ["session_id", "profile_id"],
        ["profiles.session_id", "profiles.id"],
        ondelete="CASCADE",
    ),
    task_fk("task_id"),
    UniqueConstraint("task_id", "role"),
    CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
    Index("ix_messages_profile_id_created_at", "profile_id", "created_at"),
)

diagnoses = Table(
    "diagnoses",
    metadata,
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
        ["profile_versions.session_id", "profile_versions.profile_id", "profile_versions.version"],
        deferrable=True,
        initially="DEFERRED",
    ),
)

diagnosis_items = Table(
    "diagnosis_items",
    metadata,
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
    Index("ix_diagnosis_items_diagnosis_id", "diagnosis_id"),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    uuid("session_id", primary_key=True),
    Column("key", Text, primary_key=True),
    Column("operation", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("resource_type", Text, nullable=False),
    uuid("resource_id", nullable=False),
    time("created_at", nullable=False),
    session_fk(),
    Index("ix_idempotency_keys_created_at", "created_at"),
)

file_cleanup = Table(
    "file_cleanup",
    metadata,
    Column("storage_key", Text, primary_key=True),
    time("created_at", nullable=False),
    Column("attempt", Integer, nullable=False),
    time("next_attempt_at", nullable=False),
    CheckConstraint("attempt >= 0", name="ck_file_cleanup_attempt"),
    Index("ix_file_cleanup_next_attempt_at", "next_attempt_at"),
)
