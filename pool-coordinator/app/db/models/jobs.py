from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum
from sqlalchemy import ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.enums import AssignmentStatus, JobStatus, JobType
from app.db.models.mixins import TimestampMixin
from app.db.session import Base


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[JobType] = mapped_column(
        SqlEnum(JobType, name="job_type_enum", native_enum=False),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        SqlEnum(JobStatus, name="job_status_enum", native_enum=False),
        nullable=False,
        server_default=JobStatus.QUEUED.value,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    assignments: Mapped[list[Assignment]] = relationship(back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_job_type", "job_type"),
        Index("ix_jobs_priority", "priority"),
    )


class Assignment(TimestampMixin, Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        SqlEnum(AssignmentStatus, name="assignment_status_enum", native_enum=False),
        nullable=False,
        server_default=AssignmentStatus.ASSIGNED.value,
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    job: Mapped[Job] = relationship(back_populates="assignments")
    result: Mapped[Result | None] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_assignments_job_id", "job_id"),
        Index("ix_assignments_worker_id", "worker_id"),
        Index("ix_assignments_nonce", "nonce"),
        Index("ix_assignments_status", "status"),
    )


class Result(TimestampMixin, Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="result")

    __table_args__ = (Index("ix_results_assignment_id", "assignment_id"),)
