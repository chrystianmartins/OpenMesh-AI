from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, User
from app.db.models.enums import OwnerType, Role


def test_register_success_for_client_creates_account(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/auth/register",
        json={"email": "client@test.local", "password": "super-secret-password", "role": "client"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["email"] == "client@test.local"
    assert payload["role"] == "client"

    user = db_session.scalar(select(User).where(User.email == "client@test.local"))
    assert user is not None
    assert user.role == Role.CLIENT
    assert user.password_hash is not None
    assert "super-secret-password" not in user.password_hash

    account = db_session.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.USER,
            Account.owner_id == user.id,
        )
    )
    assert account is not None


def test_register_success_for_worker_owner_does_not_create_account(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/auth/register",
        json={"email": "owner@test.local", "password": "super-secret-password", "role": "worker_owner"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "worker_owner"

    user = db_session.scalar(select(User).where(User.email == "owner@test.local"))
    assert user is not None
    assert user.role == Role.WORKER_OWNER

    account = db_session.scalar(select(Account).where(Account.owner_id == user.id))
    assert account is None


def test_register_invalid_role_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"email": "bad-role@test.local", "password": "super-secret-password", "role": "admin"},
    )

    assert response.status_code in {400, 422}


def test_login_success(client: TestClient, create_user) -> None:
    create_user(email="login-ok@test.local", password="super-secret-password", role=Role.CLIENT)

    response = client.post(
        "/auth/login",
        json={"email": "login-ok@test.local", "password": "super-secret-password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["refresh_token"]


def test_login_invalid_password_fails(client: TestClient, create_user) -> None:
    create_user(email="login-fail@test.local", password="correct-password", role=Role.CLIENT)

    response = client.post(
        "/auth/login",
        json={"email": "login-fail@test.local", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
