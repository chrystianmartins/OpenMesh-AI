from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MeResponse(BaseModel):
    user_id: int
    role: str
    client_id: int | None = None
    worker_owner_id: int | None = None
    account_id: int | None = None
    balance: Decimal
    currency: str = "USD"


class BalanceResponse(BaseModel):
    account_id: int | None = None
    balance: Decimal
    currency: str


class LedgerEntryResponse(BaseModel):
    id: int
    amount: Decimal
    entry_type: str
    job_id: int | None = None
    assignment_id: int | None = None
    details: dict[str, object] | None = None
    created_at: datetime


class LedgerPageResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[LedgerEntryResponse]


class AdminFinanceSummaryResponse(BaseModel):
    total_accounts: int
    total_ledger_entries: int
    total_volume_tokens: Decimal
    pool_balance_tokens: Decimal
