"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-02-08 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


role_enum = sa.Enum("admin", "operator", "user", name="role_enum", native_enum=False, create_constraint=True)
worker_status_enum = sa.Enum(
    "online",
    "offline",
    "draining",
    "maintenance",
    name="worker_status_enum",
    native_enum=False,
    create_constraint=True,
)
job_type_enum = sa.Enum(
    "inference",
    "fine_tuning",
    "embedding",
    name="job_type_enum",
    native_enum=False,
    create_constraint=True,
)
job_status_enum = sa.Enum(
    "queued",
    "running",
    "completed",
    "failed",
    "canceled",
    name="job_status_enum",
    native_enum=False,
    create_constraint=True,
)
assignment_status_enum = sa.Enum(
    "pending",
    "started",
    "completed",
    "failed",
    "canceled",
    name="assignment_status_enum",
    native_enum=False,
    create_constraint=True,
)
owner_type_enum = sa.Enum("user", "worker", "system", name="owner_type_enum", native_enum=False, create_constraint=True)


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", role_enum, nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_role", "users", ["role"], unique=False)

    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", worker_status_enum, nullable=False, server_default="offline"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_workers_last_heartbeat_at", "workers", ["last_heartbeat_at"], unique=False)
    op.create_index("ix_workers_status", "workers", ["status"], unique=False)

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_type", owner_type_enum, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False, server_default="USD"),
        sa.Column("balance", sa.Numeric(precision=18, scale=8), nullable=False, server_default="0"),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_type", "owner_id", "currency", name="uq_accounts_owner_currency"),
    )
    op.create_index("ix_accounts_owner_lookup", "accounts", ["owner_type", "owner_id"], unique=False)

    op.create_table(
        "pool_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_job_timeout_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("assignment_retry_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("cleanup_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("enable_auto_scaling", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("job_type", job_type_enum, nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("minimum_charge", sa.Numeric(precision=18, scale=8), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_pricing_rules_is_active", "pricing_rules", ["is_active"], unique=False)
    op.create_index("ix_pricing_rules_job_type", "pricing_rules", ["job_type"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("job_type", job_type_enum, nullable=False),
        sa.Column("status", job_status_enum, nullable=False, server_default="queued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"], unique=False)
    op.create_index("ix_jobs_priority", "jobs", ["priority"], unique=False)
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_revoked", "api_keys", ["revoked"], unique=False)
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], unique=False)

    op.create_table(
        "worker_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("heartbeat_timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("pull_interval_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("accept_new_assignments", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id"),
    )
    op.create_index("ix_worker_settings_worker_id", "worker_settings", ["worker_id"], unique=False)

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("status", assignment_status_enum, nullable=False, server_default="pending"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost", sa.Numeric(precision=18, scale=8), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignments_job_id", "assignments", ["job_id"], unique=False)
    op.create_index("ix_assignments_status", "assignments", ["status"], unique=False)
    op.create_index("ix_assignments_worker_id", "assignments", ["worker_id"], unique=False)

    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("artifact_uri", sa.String(length=512), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id"),
    )
    op.create_index("ix_results_assignment_id", "results", ["assignment_id"], unique=False)

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ledger_entries_account_id", "ledger_entries", ["account_id"], unique=False)
    op.create_index("ix_ledger_entries_assignment_id", "ledger_entries", ["assignment_id"], unique=False)
    op.create_index("ix_ledger_entries_job_id", "ledger_entries", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_job_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_assignment_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_account_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")

    op.drop_index("ix_results_assignment_id", table_name="results")
    op.drop_table("results")

    op.drop_index("ix_assignments_worker_id", table_name="assignments")
    op.drop_index("ix_assignments_status", table_name="assignments")
    op.drop_index("ix_assignments_job_id", table_name="assignments")
    op.drop_table("assignments")

    op.drop_index("ix_worker_settings_worker_id", table_name="worker_settings")
    op.drop_table("worker_settings")

    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_revoked", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_priority", table_name="jobs")
    op.drop_index("ix_jobs_job_type", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_pricing_rules_job_type", table_name="pricing_rules")
    op.drop_index("ix_pricing_rules_is_active", table_name="pricing_rules")
    op.drop_table("pricing_rules")

    op.drop_table("pool_settings")

    op.drop_index("ix_accounts_owner_lookup", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_workers_status", table_name="workers")
    op.drop_index("ix_workers_last_heartbeat_at", table_name="workers")
    op.drop_table("workers")

    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")
