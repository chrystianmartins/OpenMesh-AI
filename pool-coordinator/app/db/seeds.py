from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.auth import User
from app.db.models.enums import JobType, Role
from app.db.models.pool import PoolSettings, PricingRule
from app.db.session import transactional_session

POOL_SETTINGS_SINGLETON_ID = 1


@dataclass(frozen=True)
class DefaultPricingRule:
    name: str
    job_type: JobType
    unit_price: Decimal
    minimum_charge: Decimal


DEFAULT_PRICING_RULES: tuple[DefaultPricingRule, ...] = (
    DefaultPricingRule(
        name="EMBED",
        job_type=JobType.EMBEDDING,
        unit_price=Decimal("0.00010000"),
        minimum_charge=Decimal("0.00000000"),
    ),
    DefaultPricingRule(
        name="RANK",
        job_type=JobType.INFERENCE,
        unit_price=Decimal("0.00020000"),
        minimum_charge=Decimal("0.00000000"),
    ),
)

password_hasher = PasswordHasher()


def _upsert_admin_user(db: Session) -> None:
    app_settings = get_settings()
    existing_user = db.scalar(select(User).where(User.email == app_settings.admin_email))

    if existing_user is None:
        db.add(
            User(
                email=app_settings.admin_email,
                role=Role.ADMIN,
                is_active=True,
                password_hash=password_hasher.hash(app_settings.admin_password),
            )
        )
        return

    if existing_user.role != Role.ADMIN:
        existing_user.role = Role.ADMIN

    if not existing_user.is_active:
        existing_user.is_active = True

    if existing_user.password_hash is None:
        existing_user.password_hash = password_hasher.hash(app_settings.admin_password)
        return

    if password_hasher.check_needs_rehash(existing_user.password_hash):
        existing_user.password_hash = password_hasher.hash(app_settings.admin_password)


def _upsert_pool_settings(db: Session) -> None:
    settings_row = db.get(PoolSettings, POOL_SETTINGS_SINGLETON_ID)
    if settings_row is not None:
        return

    db.add(
        PoolSettings(
            id=POOL_SETTINGS_SINGLETON_ID,
            default_job_timeout_seconds=900,
            assignment_retry_limit=3,
            cleanup_interval_seconds=300,
            enable_auto_scaling=True,
        )
    )


def _upsert_pricing_rules(db: Session) -> None:
    now = datetime.now(UTC)

    for rule in DEFAULT_PRICING_RULES:
        existing_rule = db.scalar(select(PricingRule).where(PricingRule.name == rule.name))
        if existing_rule is None:
            db.add(
                PricingRule(
                    name=rule.name,
                    job_type=rule.job_type,
                    unit_price=rule.unit_price,
                    minimum_charge=rule.minimum_charge,
                    is_active=True,
                    effective_from=now,
                    effective_to=None,
                )
            )
            continue

        existing_rule.is_active = True


def seed_defaults(db: Session) -> None:
    _upsert_admin_user(db)
    _upsert_pool_settings(db)
    _upsert_pricing_rules(db)


def run_seed() -> None:
    with transactional_session() as db:
        seed_defaults(db)


if __name__ == "__main__":
    run_seed()
