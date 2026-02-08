from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User
from app.db.models.pool import PoolSettings, PricingRule
from app.db.seeds import seed_defaults
from app.db.session import Base


def test_seed_defaults_is_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "super-secret-password")
    get_settings.cache_clear()

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_defaults(session)
        session.commit()

    with Session(engine) as session:
        seed_defaults(session)
        session.commit()

    with Session(engine) as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].email == "admin@test.local"
        assert users[0].role.value == "admin"
        assert users[0].password_hash is not None
        assert not users[0].password_hash.startswith("super-secret-password")

        pool_settings_rows = session.scalars(select(PoolSettings)).all()
        assert len(pool_settings_rows) == 1
        assert pool_settings_rows[0].id == 1

        pricing_rules = session.scalars(select(PricingRule)).all()
        assert len(pricing_rules) == 2
        assert {rule.name for rule in pricing_rules} == {"EMBED", "RANK"}
        assert all(rule.is_active for rule in pricing_rules)
