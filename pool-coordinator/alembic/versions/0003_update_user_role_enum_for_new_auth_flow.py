"""update user role enum for new auth flow

Revision ID: 0003_update_user_role_enum_for_new_auth_flow
Revises: 0002_add_user_password_hash
Create Date: 2026-02-08 00:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_update_user_role_enum_for_new_auth_flow"
down_revision: str | None = "0002_add_user_password_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


old_role_enum = sa.Enum(
    "admin",
    "operator",
    "user",
    name="role_enum",
    native_enum=False,
    create_constraint=True,
)
new_role_enum = sa.Enum(
    "client",
    "worker_owner",
    name="role_enum",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(32) USING role::text")

    op.execute("UPDATE users SET role = 'worker_owner' WHERE role IN ('admin', 'operator')")
    op.execute("UPDATE users SET role = 'client' WHERE role = 'user'")

    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS role_enum")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role_enum")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(length=32),
            type_=new_role_enum,
            existing_nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(32) USING role::text")

    op.execute("UPDATE users SET role = 'operator' WHERE role = 'worker_owner'")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'client'")

    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS role_enum")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role_enum")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(length=32),
            type_=old_role_enum,
            existing_nullable=False,
            server_default="user",
        )
