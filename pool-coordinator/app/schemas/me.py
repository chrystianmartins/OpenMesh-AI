from __future__ import annotations

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
