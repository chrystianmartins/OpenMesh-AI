from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.accounting import Account, LedgerEntry
from app.db.models.enums import AssignmentStatus, JobStatus, OwnerType, VerificationStatus
from app.db.models.jobs import Assignment, Result
from app.db.models.pool import PoolSettings, PricingRule

POOL_ACCOUNT_OWNER_ID = 1
TOKEN_CURRENCY = "TOK"


@dataclass(frozen=True)
class FinanceSummary:
    total_accounts: int
    total_ledger_entries: int
    total_volume_tokens: Decimal
    pool_balance_tokens: Decimal


def _get_or_create_account(db: Session, *, owner_type: OwnerType, owner_id: int, currency: str) -> Account:
    account = db.scalar(
        select(Account).where(
            Account.owner_type == owner_type,
            Account.owner_id == owner_id,
            Account.currency == currency,
        )
    )
    if account is not None:
        return account

    account = Account(owner_type=owner_type, owner_id=owner_id, currency=currency, balance=Decimal("0"))
    db.add(account)
    db.flush()
    return account


def estimate_payload_units(payload: dict[str, object]) -> int:
    payload_chars = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    raw_units = (Decimal(payload_chars) / Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return max(1, int(raw_units))


def _active_pricing_rule(db: Session, *, job_type: object) -> PricingRule | None:
    return db.scalar(
        select(PricingRule)
        .where(
            PricingRule.job_type == job_type,
            PricingRule.is_active.is_(True),
        )
        .order_by(PricingRule.effective_from.desc(), PricingRule.id.desc())
    )


def _create_ledger_entry(
    db: Session,
    *,
    account: Account,
    amount: Decimal,
    reason: str,
    assignment: Assignment,
    details: dict[str, object],
) -> None:
    account.balance = (account.balance or Decimal("0")) + amount
    db.add(
        LedgerEntry(
            account_id=account.id,
            job_id=assignment.job_id,
            assignment_id=assignment.id,
            amount=amount,
            entry_type=reason,
            details=details,
        )
    )


def apply_job_verification_accounting(db: Session, *, assignment: Assignment, result: Result) -> None:
    if result.verification_status != VerificationStatus.VERIFIED:
        return
    if assignment.worker is None or assignment.job is None or assignment.job.created_by_user_id is None:
        return
    if assignment.status in {AssignmentStatus.FAILED, AssignmentStatus.CANCELED}:
        return
    if assignment.job.status in {JobStatus.FAILED, JobStatus.CANCELED}:
        return

    existing_entry = db.scalar(
        select(LedgerEntry.id).where(
            LedgerEntry.assignment_id == assignment.id,
            LedgerEntry.entry_type == "job_charge",
        )
    )
    if existing_entry is not None:
        return

    pricing_rule = _active_pricing_rule(db, job_type=assignment.job.job_type)
    if pricing_rule is None:
        return

    pool_settings = db.get(PoolSettings, 1)
    pool_fee_bps = pool_settings.pool_fee_bps if pool_settings is not None else 0

    units = estimate_payload_units(assignment.job.payload)
    unit_cost_tokens = pricing_rule.unit_cost_tokens if pricing_rule.unit_cost_tokens is not None else Decimal("0")
    cost = (Decimal(units) * unit_cost_tokens).quantize(Decimal("0.00000001"))
    pool_fee = (cost * Decimal(pool_fee_bps) / Decimal(10_000)).quantize(Decimal("0.00000001"))
    worker_reward = cost - pool_fee

    client_account = _get_or_create_account(
        db,
        owner_type=OwnerType.USER,
        owner_id=assignment.job.created_by_user_id,
        currency=TOKEN_CURRENCY,
    )
    pool_account = _get_or_create_account(
        db,
        owner_type=OwnerType.SYSTEM,
        owner_id=POOL_ACCOUNT_OWNER_ID,
        currency=TOKEN_CURRENCY,
    )
    worker_owner_account = _get_or_create_account(
        db,
        owner_type=OwnerType.USER,
        owner_id=assignment.worker.owner_user_id,
        currency=TOKEN_CURRENCY,
    )

    common_details: dict[str, object] = {
        "units": units,
        "unit_cost_tokens": str(unit_cost_tokens),
        "pool_fee_bps": pool_fee_bps,
        "cost": str(cost),
    }

    _create_ledger_entry(
        db,
        account=client_account,
        amount=-cost,
        reason="job_charge",
        assignment=assignment,
        details=common_details,
    )
    _create_ledger_entry(
        db,
        account=pool_account,
        amount=pool_fee,
        reason="pool_fee",
        assignment=assignment,
        details=common_details,
    )
    _create_ledger_entry(
        db,
        account=worker_owner_account,
        amount=worker_reward,
        reason="worker_reward",
        assignment=assignment,
        details=common_details,
    )




def record_interpool_fee_placeholder(
    db: Session,
    *,
    job_id: int | None,
    peer_id: str,
    direction: str,
    details: dict[str, object] | None = None,
) -> None:
    pool_account = _get_or_create_account(
        db,
        owner_type=OwnerType.SYSTEM,
        owner_id=POOL_ACCOUNT_OWNER_ID,
        currency=TOKEN_CURRENCY,
    )

    payload: dict[str, object] = {"peer_id": peer_id, "direction": direction}
    if details:
        payload.update(details)

    db.add(
        LedgerEntry(
            account_id=pool_account.id,
            job_id=job_id,
            assignment_id=None,
            amount=Decimal("0"),
            entry_type="interpool_fee",
            details=payload,
        )
    )

def get_finance_summary(db: Session) -> FinanceSummary:
    total_accounts = int(db.scalar(select(func.count()).select_from(Account)) or 0)
    total_ledger_entries = int(db.scalar(select(func.count()).select_from(LedgerEntry)) or 0)
    total_volume_tokens = (
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.entry_type != "job_charge")
        )
        or Decimal("0")
    )

    pool_account = db.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.SYSTEM,
            Account.owner_id == POOL_ACCOUNT_OWNER_ID,
            Account.currency == TOKEN_CURRENCY,
        )
    )

    return FinanceSummary(
        total_accounts=total_accounts,
        total_ledger_entries=total_ledger_entries,
        total_volume_tokens=Decimal(total_volume_tokens),
        pool_balance_tokens=pool_account.balance if pool_account is not None else Decimal("0"),
    )
