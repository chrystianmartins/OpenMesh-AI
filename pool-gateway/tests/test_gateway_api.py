from __future__ import annotations

from collections import deque
from typing import Any

from fastapi.testclient import TestClient

from app.main import app


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeCoordinatorClient:
    def __init__(self, responses: dict[tuple[str, str], list[FakeResponse]]) -> None:
        self._responses = {k: deque(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str]] = []

    async def post(self, path: str, **_: Any) -> FakeResponse:
        self.calls.append(("POST", path))
        queue = self._responses[("POST", path)]
        return queue.popleft() if len(queue) > 1 else queue[0]

    async def get(self, path: str, **_: Any) -> FakeResponse:
        self.calls.append(("GET", path))
        queue = self._responses[("GET", path)]
        return queue.popleft() if len(queue) > 1 else queue[0]

    async def aclose(self) -> None:
        return None


def test_embed_success() -> None:
    with TestClient(app) as client:
        app.state.coordinator_client = FakeCoordinatorClient(
            {
                ("POST", "/internal/jobs/create"): [FakeResponse(201, {"job_id": "job-1"})],
                ("GET", "/internal/jobs/job-1"): [
                    FakeResponse(200, {"status": "running"}),
                    FakeResponse(200, {"status": "verified", "output": [0.1, 0.2]}),
                ],
            }
        )
        response = client.post("/v1/embed", headers={"X-API-Key": "dev-key"}, json={"text": "hello"})

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-1", "output": [0.1, 0.2]}


def test_embed_enforces_text_max_length() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/embed", headers={"X-API-Key": "dev-key"}, json={"text": "a" * 20_001})

    assert response.status_code == 422


def test_rank_enforces_texts_bounds() -> None:
    with TestClient(app) as client:
        too_many = client.post(
            "/v1/rank",
            headers={"X-API-Key": "dev-key"},
            json={"query": "q", "texts": ["a"] * 33},
        )
        too_large_item = client.post(
            "/v1/rank",
            headers={"X-API-Key": "dev-key"},
            json={"query": "q", "texts": ["a" * 10_001]},
        )

    assert too_many.status_code == 422
    assert too_large_item.status_code == 422


def test_insufficient_balance_returns_402() -> None:
    with TestClient(app) as client:
        app.state.coordinator_client = FakeCoordinatorClient(
            {
                ("POST", "/internal/jobs/create"): [FakeResponse(402, {"detail": "insufficient"})],
            }
        )
        response = client.post(
            "/v1/rank",
            headers={"X-API-Key": "dev-key"},
            json={"query": "a", "texts": ["b"]},
        )

    assert response.status_code == 402
    assert response.json()["detail"] == "Insufficient balance"


def test_timeout_triggers_cancel_and_returns_503() -> None:
    with TestClient(app) as client:
        app.state.settings.poll_timeout_seconds = 0.01
        app.state.settings.poll_interval_seconds = 0.0
        fake = FakeCoordinatorClient(
            {
                ("POST", "/internal/jobs/create"): [FakeResponse(201, {"job_id": "job-timeout"})],
                ("GET", "/internal/jobs/job-timeout"): [FakeResponse(200, {"status": "running"})] * 10,
                ("POST", "/internal/jobs/job-timeout/cancel"): [FakeResponse(200, {"status": "cancelled"})],
            }
        )
        app.state.coordinator_client = fake

        response = client.post("/v1/embed", headers={"X-API-Key": "dev-key"}, json={"text": "hello"})

    assert response.status_code == 503
    assert ("POST", "/internal/jobs/job-timeout/cancel") in fake.calls


def test_rate_limit_by_api_key_and_ip(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_API_KEYS", "client-a:key-a,client-b:key-b")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE_API_KEY", "2")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE_IP", "1")

    with TestClient(app) as client:
        app.state.coordinator_client = FakeCoordinatorClient(
            {
                ("POST", "/internal/jobs/create"): [FakeResponse(201, {"job_id": "job-1"})],
                ("GET", "/internal/jobs/job-1"): [FakeResponse(200, {"status": "verified", "output": [1]})],
            }
        )
        ok = client.post("/v1/embed", headers={"X-API-Key": "key-a"}, json={"text": "first"})
        limited_ip = client.post("/v1/embed", headers={"X-API-Key": "key-b"}, json={"text": "second"})

    assert ok.status_code == 200
    assert limited_ip.status_code == 429
