from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiKey
from app.db.models.enums import Role


def test_client_can_create_api_key_and_secret_is_not_stored(
    client: TestClient,
    db_session: Session,
    create_user,
    auth_headers,
) -> None:
    create_user(email="api-client@test.local", password="super-secret-password", role=Role.CLIENT)
    headers = auth_headers("api-client@test.local", "super-secret-password")

    response = client.post("/auth/api-keys", json={"name": "primary-key"}, headers=headers)

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "primary-key"
    assert payload["key"].startswith("omk_")
    assert payload["prefix"] == payload["key"][:12]

    row = db_session.scalar(select(ApiKey).where(ApiKey.id == payload["id"]))
    assert row is not None
    assert row.prefix == payload["prefix"]
    assert row.key_hash != payload["key"]
    assert payload["key"] not in row.key_hash


def test_api_key_secret_is_one_time_returned(client: TestClient, create_user, auth_headers) -> None:
    create_user(email="api-once@test.local", password="super-secret-password", role=Role.CLIENT)
    headers = auth_headers("api-once@test.local", "super-secret-password")

    create_response = client.post("/auth/api-keys", json={"name": "once-key"}, headers=headers)
    assert create_response.status_code == 201
    created_key = create_response.json()["key"]

    me_response = client.get("/me", headers=headers)
    assert me_response.status_code == 200
    assert "key" not in me_response.json()

    duplicate_name_response = client.post("/auth/api-keys", json={"name": "once-key"}, headers=headers)
    assert duplicate_name_response.status_code in {201, 409}
    if duplicate_name_response.status_code == 201:
        assert duplicate_name_response.json()["key"] != created_key
