from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
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
    status: Mapped[WorkerStatus] = mapped_column(
        SqlEnum(WorkerStatus, name="worker_status_enum", native_enum=False),
        nullable=False,
        server_default=WorkerStatus.OFFLINE.value,
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    settings: Mapped[WorkerSettings] = relationship(
        back_populates="worker",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_workers_status", "status"),
        Index("ix_workers_last_heartbeat_at", "last_heartbeat_at"),
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
