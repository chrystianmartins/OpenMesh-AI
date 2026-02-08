"""add api key prefix

Revision ID: 0004_add_api_key_prefix
Revises: 0003_update_user_role_enum_for_new_auth_flow
Create Date: 2026-02-08 00:40:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_add_api_key_prefix"
down_revision: str | None = "0003_update_user_role_enum_for_new_auth_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(sa.Column("prefix", sa.String(length=32), nullable=True))

    op.execute("UPDATE api_keys SET prefix = substring(key_hash, 1, 12)")

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.alter_column("prefix", existing_type=sa.String(length=32), nullable=False)
        batch_op.create_index("ix_api_keys_prefix", ["prefix"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_index("ix_api_keys_prefix")
        batch_op.drop_column("prefix")
