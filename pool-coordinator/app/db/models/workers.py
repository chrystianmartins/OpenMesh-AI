from __future__ import annotations

from datetime import datetime

from typing import Any

from sqlalchemy import DateTime, JSON
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.enums import WorkerStatus
from app.db.models.mixins import TimestampMixin
from app.db.session import Base


class Worker(TimestampMixin, Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        SqlEnum(WorkerStatus, name="worker_status_enum", native_enum=False),
        nullable=False,
        server_default=WorkerStatus.OFFLINE.value,
    )
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    specs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Canonical format: base64url-encoded public key.
    public_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    settings: Mapped[WorkerSettings] = relationship(
        back_populates="worker",
        cascade="all, delete-orphan",
        uselist=False,
    )
    heartbeats: Mapped[list[WorkerHeartbeat]] = relationship(
        back_populates="worker",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_workers_owner_user_id", "owner_user_id"),
        Index("ix_workers_status", "status"),
        Index("ix_workers_last_seen_at", "last_seen_at"),
    )


class WorkerSettings(TimestampMixin, Base):
    __tablename__ = "worker_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    heartbeat_timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="30",
    )
    pull_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    accept_new_assignments: Mapped[bool] = mapped_column(nullable=False, server_default="true")

    worker: Mapped[Worker] = relationship(back_populates="settings")

    __table_args__ = (Index("ix_worker_settings_worker_id", "worker_id"),)


class WorkerHeartbeat(TimestampMixin, Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    worker: Mapped[Worker] = relationship(back_populates="heartbeats")

    __table_args__ = (
        Index("ix_worker_heartbeats_worker_id", "worker_id"),
        Index("ix_worker_heartbeats_recorded_at", "recorded_at"),
    )
