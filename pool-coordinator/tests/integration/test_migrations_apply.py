from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def test_migrations_apply_and_core_schema_exists(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    expected_tables = {
        "users",
        "workers",
        "worker_settings",
        "jobs",
        "assignments",
        "results",
        "pool_settings",
        "pricing_rules",
        "accounts",
        "ledger_entries",
        "api_keys",
    }

    assert expected_tables.issubset(set(inspector.get_table_names()))

    users_checks = inspector.get_check_constraints("users")
    workers_checks = inspector.get_check_constraints("workers")
    jobs_checks = inspector.get_check_constraints("jobs")
    assignments_checks = inspector.get_check_constraints("assignments")

    assert any("role" in (check.get("sqltext") or "") for check in users_checks)
    assert any("status" in (check.get("sqltext") or "") for check in workers_checks)
    assert any("status" in (check.get("sqltext") or "") for check in jobs_checks)
    assert any("status" in (check.get("sqltext") or "") for check in assignments_checks)

    with migrated_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert revision == "0001_initial_schema"
