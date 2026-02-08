"""add verification and audit controls

Revision ID: 0007_verification_and_audit_controls
Revises: 0006_add_assigned_assignment_status
Create Date: 2026-02-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0007_verification_and_audit_controls"
down_revision: str | None = "0006_add_assigned_assignment_status"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


verification_status_enum = sa.Enum(
    "pending",
    "verified",
    "disputed",
    "rejected",
    name="verification_status_enum",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("canonical_expected_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("is_audit_job", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    with op.batch_alter_table("results") as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                verification_status_enum,
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("verification_score", sa.Numeric(precision=6, scale=5), nullable=True))

    with op.batch_alter_table("pool_settings") as batch_op:
        batch_op.add_column(sa.Column("audit_interval_jobs", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("audit_job_rate_bps", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("fraud_ban_threshold", sa.Integer(), nullable=False, server_default="2"))
        batch_op.add_column(
            sa.Column(
                "embed_similarity_threshold",
                sa.Numeric(precision=6, scale=5),
                nullable=False,
                server_default="0.985",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("pool_settings") as batch_op:
        batch_op.drop_column("embed_similarity_threshold")
        batch_op.drop_column("fraud_ban_threshold")
        batch_op.drop_column("audit_job_rate_bps")
        batch_op.drop_column("audit_interval_jobs")

    with op.batch_alter_table("results") as batch_op:
        batch_op.drop_column("verification_score")
        batch_op.drop_column("verification_status")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("is_audit_job")
        batch_op.drop_column("canonical_expected_hash")
