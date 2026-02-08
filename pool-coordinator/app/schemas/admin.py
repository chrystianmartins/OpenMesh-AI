from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class AdminEmissionStatusResponse(BaseModel):
    date: date
    cap_tokens: Decimal
    emitted_today_tokens: Decimal
    remaining_tokens: Decimal
    run_completed: bool


class AdminEmissionRunResponse(BaseModel):
    target_day: date
    cap_tokens: Decimal
    emitted_tokens: Decimal
    workers_rewarded: int
