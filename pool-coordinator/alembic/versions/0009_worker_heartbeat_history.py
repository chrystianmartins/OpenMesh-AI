"""add worker heartbeat history table

Revision ID: 0009_worker_heartbeat_history
Revises: 0008_token_accounting_columns
Create Date: 2026-02-08 01:35:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_worker_heartbeat_history"
down_revision: str | None = "0008_token_accounting_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_heartbeats_worker_id", "worker_heartbeats", ["worker_id"], unique=False)
    op.create_index("ix_worker_heartbeats_recorded_at", "worker_heartbeats", ["recorded_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_recorded_at", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_worker_id", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
