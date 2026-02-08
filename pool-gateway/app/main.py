from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger("pool-gateway")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] request_id=%(request_id)s %(message)s",
)


class RequestLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("request_id", self.extra.get("request_id", "-"))
        return msg, kwargs


@dataclass
class Settings:
    coordinator_url: str
    internal_token: str
    api_keys: dict[str, str]
    rate_limit_per_minute: int
    poll_timeout_seconds: float
    poll_interval_seconds: float


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

            bucket.append(now)


class EmbedRequest(BaseModel):
    text: str = Field(min_length=1)


class RankRequest(BaseModel):
    query: str = Field(min_length=1)
    texts: list[str] = Field(min_length=1)


def load_settings() -> Settings:
    raw_keys = os.getenv("GATEWAY_API_KEYS", "client-dev:dev-key")
    api_keys: dict[str, str] = {}
    for item in raw_keys.split(","):
        if not item.strip():
            continue
        client_id, _, api_key = item.partition(":")
        if not client_id or not api_key:
            continue
        api_keys[api_key.strip()] = client_id.strip()

    return Settings(
        coordinator_url=os.getenv("COORDINATOR_URL", "http://localhost:8001"),
        internal_token=os.getenv("COORDINATOR_INTERNAL_TOKEN", "dev-internal-token"),
        api_keys=api_keys,
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
        poll_timeout_seconds=float(os.getenv("POLL_TIMEOUT_SECONDS", "20")),
        poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "1.0")),
    )


async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    app.state.rate_limiter = RateLimiter(max_requests=app.state.settings.rate_limit_per_minute)
    app.state.coordinator_client = httpx.AsyncClient(base_url=app.state.settings.coordinator_url, timeout=5.0)
    yield
    await app.state.coordinator_client.aclose()


app = FastAPI(title="OpenMesh Pool Gateway", version="0.1.0", lifespan=lifespan)


async def get_client_id(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> str:
    request_id = getattr(request.state, "request_id", "-")
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client_id = settings.api_keys.get(x_api_key)
    if client_id is None:
        log.warning("authentication failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    request.app.state.rate_limiter.check(x_api_key)
    return client_id


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})

    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("method=%s path=%s elapsed_ms=%.2f", request.method, request.url.path, elapsed_ms)

    response.headers["X-Request-ID"] = request_id
    return response


async def _create_job(request: Request, client_id: str, job_type: str, payload: dict[str, Any]) -> str:
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client

    started = time.perf_counter()
    response = await client.post(
        "/internal/jobs/create",
        headers={"Authorization": f"Bearer {settings.internal_token}", "X-Request-ID": request_id},
        json={"client_id": client_id, "job_type": job_type, "payload": payload},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info("coordinator_create elapsed_ms=%.2f status=%s", elapsed_ms, response.status_code)

    if response.status_code in {status.HTTP_402_PAYMENT_REQUIRED, status.HTTP_429_TOO_MANY_REQUESTS}:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient balance")
    response.raise_for_status()
    data = response.json()
    return str(data["job_id"])


async def _cancel_job(request: Request, job_id: str) -> None:
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    try:
        await client.post(
            f"/internal/jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {settings.internal_token}", "X-Request-ID": request_id},
            json={"reason": "gateway_timeout"},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("cancel failed job_id=%s error=%s", job_id, exc)


async def _wait_for_verification(request: Request, job_id: str) -> dict[str, Any]:
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client

    timeout_at = time.monotonic() + settings.poll_timeout_seconds
    while time.monotonic() < timeout_at:
        started = time.perf_counter()
        response = await client.get(
            f"/internal/jobs/{job_id}",
            headers={"Authorization": f"Bearer {settings.internal_token}", "X-Request-ID": request_id},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("coordinator_poll elapsed_ms=%.2f status=%s", elapsed_ms, response.status_code)
        response.raise_for_status()

        job = response.json()
        if job.get("status") == "verified":
            return job
        await asyncio.sleep(settings.poll_interval_seconds)

    await _cancel_job(request, job_id)
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Verification timeout")


async def _run_job(request: Request, *, client_id: str, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = await _create_job(request, client_id, job_type, payload)
    job = await _wait_for_verification(request, job_id)
    return {"job_id": job_id, "output": job.get("output")}


@app.post("/v1/embed")
async def embed(payload: EmbedRequest, request: Request, client_id: str = Depends(get_client_id)) -> dict[str, Any]:
    return await _run_job(request, client_id=client_id, job_type="embed", payload=payload.model_dump())


@app.post("/v1/rank")
async def rank(payload: RankRequest, request: Request, client_id: str = Depends(get_client_id)) -> dict[str, Any]:
    return await _run_job(request, client_id=client_id, job_type="rank", payload=payload.model_dump())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-gateway"}
