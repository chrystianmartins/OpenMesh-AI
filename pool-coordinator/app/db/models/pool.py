from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SqlEnum
from sqlalchemy import Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.enums import JobType
from app.db.models.mixins import TimestampMixin
from app.db.session import Base


class PoolSettings(TimestampMixin, Base):
    __tablename__ = "pool_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    default_job_timeout_seconds: Mapped[int] = mapped_column(nullable=False, server_default="900")
    assignment_retry_limit: Mapped[int] = mapped_column(nullable=False, server_default="3")
    cleanup_interval_seconds: Mapped[int] = mapped_column(nullable=False, server_default="300")
    enable_auto_scaling: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    audit_interval_jobs: Mapped[int] = mapped_column(nullable=False, server_default="0")
    audit_job_rate_bps: Mapped[int] = mapped_column(nullable=False, server_default="0")
    fraud_ban_threshold: Mapped[int] = mapped_column(nullable=False, server_default="2")
    embed_similarity_threshold: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False, server_default="0.985")
    pool_fee_bps: Mapped[int] = mapped_column(nullable=False, server_default="1000")


class PricingRule(TimestampMixin, Base):
    __tablename__ = "pricing_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    job_type: Mapped[JobType] = mapped_column(
        SqlEnum(JobType, name="job_type_enum", native_enum=False),
        nullable=False,
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    unit_cost_tokens: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default="0")
    minimum_charge: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pricing_rules_job_type", "job_type"),
        Index("ix_pricing_rules_is_active", "is_active"),
    )
