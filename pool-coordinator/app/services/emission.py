from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.models.accounting import Account, LedgerEntry
from app.db.models.enums import OwnerType
from app.db.models.workers import Worker, WorkerHeartbeat
from app.services.finance import TOKEN_CURRENCY

SECONDS_PER_DAY = Decimal("86400")


class DailyEmissionStatus(TypedDict):
    date: date
    cap_tokens: Decimal
    emitted_today_tokens: Decimal
    remaining_tokens: Decimal
    run_completed: bool



@dataclass(frozen=True)
class DailyEmissionWorkerPayout:
    worker_id: int
    worker_owner_id: int
    uptime_ratio: Decimal
    reputation: Decimal
    emission_tokens: Decimal


@dataclass(frozen=True)
class DailyEmissionResult:
    target_day: date
    cap_tokens: Decimal
    emitted_tokens: Decimal
    workers_rewarded: int
    payouts: list[DailyEmissionWorkerPayout]


def _get_or_create_owner_account(db: Session, *, owner_user_id: int) -> Account:
    account = db.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.USER,
            Account.owner_id == owner_user_id,
            Account.currency == TOKEN_CURRENCY,
        )
    )
    if account is not None:
        return account

    account = Account(owner_type=OwnerType.USER, owner_id=owner_user_id, currency=TOKEN_CURRENCY, balance=Decimal("0"))
    db.add(account)
    db.flush()
    return account


def _clamp_ratio(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        return Decimal("0")
    if value > Decimal("1"):
        return Decimal("1")
    return value


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _calculate_uptime_ratio(
    db: Session,
    *,
    worker_id: int,
    timeout_seconds: int,
    window_start: datetime,
    window_end: datetime,
) -> Decimal:
    if timeout_seconds <= 0 or window_end <= window_start:
        return Decimal("0")

    points = db.scalars(
        select(WorkerHeartbeat.recorded_at)
        .where(
            WorkerHeartbeat.worker_id == worker_id,
            WorkerHeartbeat.recorded_at >= window_start,
            WorkerHeartbeat.recorded_at <= window_end,
        )
        .order_by(WorkerHeartbeat.recorded_at.asc())
    ).all()

    previous_point = db.scalar(
        select(WorkerHeartbeat.recorded_at)
        .where(
            WorkerHeartbeat.worker_id == worker_id,
            WorkerHeartbeat.recorded_at < window_start,
        )
        .order_by(WorkerHeartbeat.recorded_at.desc())
        .limit(1)
    )

    if previous_point is not None:
        points = [previous_point, *points]

    timeout = timedelta(seconds=timeout_seconds)
    covered_seconds = Decimal("0")

    for heartbeat_at in points:
        heartbeat_at = _as_utc(heartbeat_at)
        range_start = max(heartbeat_at, window_start)
        range_end = min(heartbeat_at + timeout, window_end)
        if range_end > range_start:
            covered_seconds += Decimal(str((range_end - range_start).total_seconds()))

    uptime_ratio = covered_seconds / SECONDS_PER_DAY
    return _clamp_ratio(uptime_ratio.quantize(Decimal("0.00000001")))


def get_daily_emission_status(db: Session, *, now: datetime | None = None) -> DailyEmissionStatus:
    now_utc = now or datetime.now(UTC)
    today = now_utc.date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

    emitted_today = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.entry_type == "daily_emission",
                LedgerEntry.created_at >= day_start,
            )
        )
        or Decimal("0")
    )
    cap_tokens = Decimal(str(settings.daily_emission_cap_tokens)).quantize(Decimal("0.00000001"))

    return {
        "date": today,
        "cap_tokens": cap_tokens,
        "emitted_today_tokens": emitted_today.quantize(Decimal("0.00000001")),
        "remaining_tokens": max(Decimal("0"), cap_tokens - emitted_today).quantize(Decimal("0.00000001")),
        "run_completed": emitted_today > Decimal("0"),
    }


def run_daily_emission(db: Session, *, now: datetime | None = None) -> DailyEmissionResult:
    now_utc = now or datetime.now(UTC)
    target_day = now_utc.date()
    window_end = now_utc
    window_start = now_utc - timedelta(hours=24)

    cap_tokens = Decimal(str(settings.daily_emission_cap_tokens)).quantize(Decimal("0.00000001"))
    existing_status = get_daily_emission_status(db, now=now_utc)
    remaining_cap = existing_status["remaining_tokens"]
    if remaining_cap <= Decimal("0"):
        return DailyEmissionResult(
            target_day=target_day,
            cap_tokens=cap_tokens,
            emitted_tokens=Decimal("0"),
            workers_rewarded=0,
            payouts=[],
        )

    base_tokens = Decimal(str(settings.daily_emission_base_tokens)).quantize(Decimal("0.00000001"))

    workers = db.scalars(select(Worker).options(joinedload(Worker.settings))).all()
    provisional: list[DailyEmissionWorkerPayout] = []

    for worker in workers:
        timeout_seconds = worker.settings.heartbeat_timeout_seconds if worker.settings is not None else 30
        uptime_ratio = _calculate_uptime_ratio(
            db,
            worker_id=worker.id,
            timeout_seconds=timeout_seconds,
            window_start=window_start,
            window_end=window_end,
        )
        if uptime_ratio <= Decimal("0"):
            continue

        raw_reputation = (worker.specs_json or {}).get("reputation", 0.5)
        if isinstance(raw_reputation, Decimal):
            reputation_value = raw_reputation
        elif isinstance(raw_reputation, (int, float, str)):
            reputation_value = Decimal(str(raw_reputation))
        else:
            reputation_value = Decimal("0")
        reputation = _clamp_ratio(reputation_value.quantize(Decimal("0.00000001")))
        if reputation <= Decimal("0"):
            continue

        amount = (base_tokens * uptime_ratio * reputation).quantize(Decimal("0.00000001"))
        if amount <= Decimal("0"):
            continue

        provisional.append(
            DailyEmissionWorkerPayout(
                worker_id=worker.id,
                worker_owner_id=worker.owner_user_id,
                uptime_ratio=uptime_ratio,
                reputation=reputation,
                emission_tokens=amount,
            )
        )

    provisional_total = sum((item.emission_tokens for item in provisional), Decimal("0"))
    if provisional_total <= Decimal("0"):
        return DailyEmissionResult(
            target_day=target_day,
            cap_tokens=cap_tokens,
            emitted_tokens=Decimal("0"),
            workers_rewarded=0,
            payouts=[],
        )

    scale_factor = Decimal("1") if provisional_total <= remaining_cap else (remaining_cap / provisional_total)

    payouts: list[DailyEmissionWorkerPayout] = []
    emitted_total = Decimal("0")
    for item in provisional:
        final_amount = (item.emission_tokens * scale_factor).quantize(Decimal("0.00000001"))
        if final_amount <= Decimal("0"):
            continue

        owner_account = _get_or_create_owner_account(db, owner_user_id=item.worker_owner_id)
        owner_account.balance = (owner_account.balance or Decimal("0")) + final_amount
        db.add(
            LedgerEntry(
                account_id=owner_account.id,
                job_id=None,
                assignment_id=None,
                amount=final_amount,
                entry_type="daily_emission",
                details={
                    "reason": "daily_emission",
                    "worker_id": item.worker_id,
                    "uptime_ratio": str(item.uptime_ratio),
                    "reputation": str(item.reputation),
                    "day": target_day.isoformat(),
                    "scale_factor": str(scale_factor.quantize(Decimal('0.00000001'))),
                },
            )
        )
        emitted_total += final_amount
        payouts.append(
            DailyEmissionWorkerPayout(
                worker_id=item.worker_id,
                worker_owner_id=item.worker_owner_id,
                uptime_ratio=item.uptime_ratio,
                reputation=item.reputation,
                emission_tokens=final_amount,
            )
        )

    return DailyEmissionResult(
        target_day=target_day,
        cap_tokens=cap_tokens,
        emitted_tokens=emitted_total.quantize(Decimal("0.00000001")),
        workers_rewarded=len(payouts),
        payouts=payouts,
    )
