from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_db, require_roles
from app.db.models.auth import User
from app.db.models.enums import Role
from app.schemas.me import AdminFinanceSummaryResponse
from app.services.finance import get_finance_summary

router = APIRouter(tags=["admin"])


@router.get("/admin/finance/summary", response_model=AdminFinanceSummaryResponse)
def admin_finance_summary(
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> AdminFinanceSummaryResponse:
    summary = get_finance_summary(db)
    return AdminFinanceSummaryResponse(
        total_accounts=summary.total_accounts,
        total_ledger_entries=summary.total_ledger_entries,
        total_volume_tokens=summary.total_volume_tokens,
        pool_balance_tokens=summary.pool_balance_tokens,
    )
