from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Index, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.enums import OwnerType
from app.db.models.mixins import TimestampMixin
from app.db.session import Base


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[OwnerType] = mapped_column(
        SqlEnum(OwnerType, name="owner_type_enum", native_enum=False),
        nullable=False,
    )
    owner_id: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, server_default="USD")
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "currency", name="uq_accounts_owner_currency"),
        Index("ix_accounts_owner_lookup", "owner_type", "owner_id"),
    )


class LedgerEntry(TimestampMixin, Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)

    __table_args__ = (
        Index("ix_ledger_entries_account_id", "account_id"),
        Index("ix_ledger_entries_job_id", "job_id"),
        Index("ix_ledger_entries_assignment_id", "assignment_id"),
    )
