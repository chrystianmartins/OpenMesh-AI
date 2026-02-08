from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User
from app.db.models.pool import PoolSettings, PricingRule
from app.db.seeds import seed_defaults


def test_seed_bootstrap_creates_admin_pool_settings_and_pricing_rules(
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", "bootstrap-admin@test.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "bootstrap-secret-password")
    get_settings.cache_clear()

    seed_defaults(db_session)
    db_session.commit()

    admin_user = db_session.scalar(select(User).where(User.email == "bootstrap-admin@test.local"))
    assert admin_user is not None
    assert admin_user.role.value == "worker_owner"
    assert admin_user.is_active is True
    assert admin_user.password_hash is not None
    assert not admin_user.password_hash.startswith("bootstrap-secret-password")

    pool_settings = db_session.get(PoolSettings, 1)
    assert pool_settings is not None
    assert pool_settings.assignment_retry_limit == 3
    assert pool_settings.default_job_timeout_seconds == 900
    assert pool_settings.enable_auto_scaling is True

    pricing_rules = db_session.scalars(select(PricingRule)).all()
    assert len(pricing_rules) == 2
    assert {rule.name for rule in pricing_rules} == {"EMBED", "RANK"}
    assert all(rule.is_active is True for rule in pricing_rules)
