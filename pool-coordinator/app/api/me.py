from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, get_db
from app.db.models.accounting import Account
from app.db.models.auth import User
from app.db.models.enums import OwnerType, Role
from app.schemas.me import MeResponse

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
