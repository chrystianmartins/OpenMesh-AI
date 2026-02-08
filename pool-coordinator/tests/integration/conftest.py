from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured for integration tests")
    return database_url


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: str) -> Generator[Engine, None, None]:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", test_database_url)

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(test_database_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def cleanup_tables(migrated_engine: Engine) -> Generator[None, None, None]:
    yield

    inspector = inspect(migrated_engine)
    tables = [table_name for table_name in inspector.get_table_names() if table_name != "alembic_version"]
    if not tables:
        return

    quoted_tables = ", ".join(f'"{table_name}"' for table_name in tables)
    with migrated_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session(migrated_engine: Engine) -> Generator[Session, None, None]:
    with Session(migrated_engine) as session:
        yield session
