from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.models.enums import Role


def test_worker_owner_cannot_create_api_key(client: TestClient, create_user, auth_headers) -> None:
    create_user(email="owner-rbac@test.local", password="super-secret-password", role=Role.WORKER_OWNER)
    headers = auth_headers("owner-rbac@test.local", "super-secret-password")

    response = client.post("/auth/api-keys", json={"name": "blocked-key"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/me")

    assert response.status_code == 401
