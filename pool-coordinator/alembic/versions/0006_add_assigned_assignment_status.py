"""add assigned assignment status

Revision ID: 0006_add_assigned_assignment_status
Revises: 0005_worker_identity_and_assignment_nonce
Create Date: 2026-02-08 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_add_assigned_assignment_status"
down_revision: str | None = "0005_worker_identity_and_assignment_nonce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


old_assignment_status_enum = sa.Enum(
    "pending",
    "started",
    "completed",
    "failed",
    "canceled",
    name="assignment_status_enum",
    native_enum=False,
    create_constraint=True,
)
new_assignment_status_enum = sa.Enum(
    "assigned",
    "started",
    "completed",
    "failed",
    "canceled",
    name="assignment_status_enum",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.execute("UPDATE assignments SET status = 'assigned' WHERE status = 'pending'")

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=old_assignment_status_enum,
            type_=new_assignment_status_enum,
            existing_nullable=False,
            server_default="assigned",
        )


def downgrade() -> None:
    op.execute("UPDATE assignments SET status = 'pending' WHERE status = 'assigned'")

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=new_assignment_status_enum,
            type_=old_assignment_status_enum,
            existing_nullable=False,
            server_default="pending",
        )
