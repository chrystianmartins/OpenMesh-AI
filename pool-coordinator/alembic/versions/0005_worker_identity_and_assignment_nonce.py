"""add worker identity fields and anti-replay data

Revision ID: 0005_worker_identity_and_assignment_nonce
Revises: 0004_add_api_key_prefix
Create Date: 2026-02-08 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_worker_identity_and_assignment_nonce"
down_revision: str | None = "0004_add_api_key_prefix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("region", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("specs_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("public_key", sa.String(length=1024), nullable=True))
        batch_op.alter_column(
            "last_heartbeat_at",
            new_column_name="last_seen_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_workers_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    user_id = bind.execute(sa.text("SELECT id FROM users ORDER BY id ASC LIMIT 1")).scalar_one_or_none()
    workers_without_owner = bind.execute(sa.text("SELECT COUNT(*) FROM workers WHERE owner_user_id IS NULL")).scalar_one()

    if workers_without_owner and user_id is None:
        raise RuntimeError("Migration requires at least one users row to backfill workers.owner_user_id")

    if user_id is not None:
        bind.execute(sa.text("UPDATE workers SET owner_user_id = :user_id WHERE owner_user_id IS NULL"), {"user_id": user_id})

    with op.batch_alter_table("workers") as batch_op:
        batch_op.alter_column("owner_user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_index("ix_workers_last_heartbeat_at")
        batch_op.create_index("ix_workers_owner_user_id", ["owner_user_id"], unique=False)
        batch_op.create_index("ix_workers_last_seen_at", ["last_seen_at"], unique=False)

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("nonce", sa.String(length=128), nullable=True))

    bind.execute(sa.text("UPDATE assignments SET nonce = 'legacy-' || CAST(id AS TEXT) WHERE nonce IS NULL"))

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column("nonce", existing_type=sa.String(length=128), nullable=False)
        batch_op.create_unique_constraint("uq_assignments_nonce", ["nonce"])
        batch_op.create_index("ix_assignments_nonce", ["nonce"], unique=False)

    with op.batch_alter_table("results") as batch_op:
        batch_op.add_column(sa.Column("output_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("signature", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("metrics_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("results") as batch_op:
        batch_op.drop_column("metrics_json")
        batch_op.drop_column("signature")
        batch_op.drop_column("output_hash")

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_index("ix_assignments_nonce")
        batch_op.drop_constraint("uq_assignments_nonce", type_="unique")
        batch_op.drop_column("nonce")

    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_index("ix_workers_last_seen_at")
        batch_op.drop_index("ix_workers_owner_user_id")
        batch_op.alter_column(
            "last_seen_at",
            new_column_name="last_heartbeat_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
        batch_op.drop_constraint("fk_workers_owner_user_id_users", type_="foreignkey")
        batch_op.drop_column("public_key")
        batch_op.drop_column("specs_json")
        batch_op.drop_column("region")
        batch_op.drop_column("owner_user_id")
        batch_op.create_index("ix_workers_last_heartbeat_at", ["last_heartbeat_at"], unique=False)
