from __future__ import annotations

from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_db
from app.core.security import create_access_token, hash_password
from app.db.models import User
from app.db.models.enums import Role
from app.db.session import Base
from app.main import app


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    with Session(test_engine) as session:
        yield session


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_user(db_session: Session) -> Callable[..., User]:
    def _create_user(
        *,
        email: str,
        password: str = "super-secret-password",
        role: Role = Role.CLIENT,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            role=role,
            is_active=is_active,
            password_hash=hash_password(password),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _create_user


@pytest.fixture
def auth_headers(client: TestClient) -> Callable[[str, str], dict[str, str]]:
    def _auth_headers(email: str, password: str) -> dict[str, str]:
        response = client.post("/auth/login", json={"email": email, "password": password})
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


@pytest.fixture
def token_for_user() -> Callable[[User], str]:
    def _token_for_user(user: User) -> str:
        token, _ = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role.value,
        )
        return token

    return _token_for_user
