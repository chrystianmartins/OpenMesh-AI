"""add peers table for p2p federation

Revision ID: 0010_add_peers_table_for_p2p_federation
Revises: 0009_worker_heartbeat_history
Create Date: 2026-02-08 06:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_add_peers_table_for_p2p_federation"
down_revision: str | None = "0009_worker_heartbeat_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "peers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("peer_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("shared_secret", sa.String(length=255), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("peer_id"),
    )
    op.create_index("ix_peers_peer_id", "peers", ["peer_id"], unique=False)
    op.create_index("ix_peers_last_seen", "peers", ["last_seen"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_peers_last_seen", table_name="peers")
    op.drop_index("ix_peers_peer_id", table_name="peers")
    op.drop_table("peers")
