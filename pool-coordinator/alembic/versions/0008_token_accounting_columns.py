"""add token accounting columns

Revision ID: 0008_token_accounting_columns
Revises: 0007_verification_and_audit_controls
Create Date: 2026-02-08 01:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_token_accounting_columns"
down_revision: str | None = "0007_verification_and_audit_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pool_settings") as batch_op:
        batch_op.add_column(sa.Column("pool_fee_bps", sa.Integer(), nullable=False, server_default="1000"))

    with op.batch_alter_table("pricing_rules") as batch_op:
        batch_op.add_column(
            sa.Column("unit_cost_tokens", sa.Numeric(precision=18, scale=8), nullable=False, server_default="0")
        )
    op.execute("UPDATE pricing_rules SET unit_cost_tokens = unit_price")


def downgrade() -> None:
    with op.batch_alter_table("pricing_rules") as batch_op:
        batch_op.drop_column("unit_cost_tokens")

    with op.batch_alter_table("pool_settings") as batch_op:
        batch_op.drop_column("pool_fee_bps")
