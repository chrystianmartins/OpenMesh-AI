from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, get_db
from app.db.models.accounting import Account, LedgerEntry
from app.db.models.auth import User
from app.db.models.enums import OwnerType, Role
from app.schemas.me import BalanceResponse, LedgerEntryResponse, LedgerPageResponse, MeResponse
from app.services.finance import TOKEN_CURRENCY

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    account = db.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.USER,
            Account.owner_id == current_user.id,
        )
    )

    client_id = current_user.id if current_user.role == Role.CLIENT else None
    worker_owner_id = current_user.id if current_user.role == Role.WORKER_OWNER else None

    return MeResponse(
        user_id=current_user.id,
        role=current_user.role.value,
        client_id=client_id,
        worker_owner_id=worker_owner_id,
        account_id=account.id if account is not None else None,
        balance=account.balance if account is not None else Decimal("0"),
        currency=account.currency if account is not None else "USD",
    )


@router.get("/me/balance", response_model=BalanceResponse)
def my_balance(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BalanceResponse:
    account = db.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.USER,
            Account.owner_id == current_user.id,
            Account.currency == TOKEN_CURRENCY,
        )
    )

    return BalanceResponse(
        account_id=account.id if account is not None else None,
        balance=account.balance if account is not None else Decimal("0"),
        currency=TOKEN_CURRENCY,
    )


@router.get("/me/ledger", response_model=LedgerPageResponse)
def my_ledger(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LedgerPageResponse:
    account = db.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.USER,
            Account.owner_id == current_user.id,
            Account.currency == TOKEN_CURRENCY,
        )
    )
    if account is None:
        return LedgerPageResponse(page=page, page_size=page_size, total=0, items=[])

    total = int(db.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.account_id == account.id)) or 0)
    offset = (page - 1) * page_size
    entries = db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account.id)
        .order_by(LedgerEntry.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    return LedgerPageResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=[
            LedgerEntryResponse(
                id=entry.id,
                amount=entry.amount,
                entry_type=entry.entry_type,
                job_id=entry.job_id,
                assignment_id=entry.assignment_id,
                details=entry.details,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
    )
