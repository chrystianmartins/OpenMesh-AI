from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.mixins import TimestampMixin
from app.db.session import Base


class Peer(TimestampMixin, Base):
    __tablename__ = "peers"

    id: Mapped[int] = mapped_column(primary_key=True)
    peer_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    shared_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_peers_peer_id", "peer_id"),
        Index("ix_peers_last_seen", "last_seen"),
    )
