from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, AsyncIterator, Awaitable, Callable, MutableMapping, cast

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger("pool-gateway")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level_name, logging.INFO))

    if not root_logger.handlers:
        stream_handler: logging.Handler = logging.StreamHandler()
        stream_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(stream_handler)
        return

    for existing_handler in root_logger.handlers:
        existing_handler.setFormatter(JsonFormatter())


configure_logging()


class RequestLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self,
        msg: object,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[object, MutableMapping[str, Any]]:
        extra_obj = kwargs.get("extra")
        if not isinstance(extra_obj, dict):
            extra_obj = {}
            kwargs["extra"] = extra_obj
        adapter_extra = self.extra if isinstance(self.extra, dict) else {}
        extra_obj.setdefault("request_id", adapter_extra.get("request_id", "-"))
        return msg, kwargs


class PrometheusMetrics:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._lock = Lock()
        self._request_count: dict[tuple[str, str], int] = defaultdict(int)
        self._request_latency_sum: dict[tuple[str, str], float] = defaultdict(float)

    def observe_http_request(self, path: str, method: str, elapsed_seconds: float) -> None:
        if not self.enabled:
            return
        key = (path, method)
        with self._lock:
            self._request_count[key] += 1
            self._request_latency_sum[key] += elapsed_seconds

    def render(self) -> str:
        if not self.enabled:
            return "# metrics disabled\n"

        lines = [
            "# HELP http_requests_total Total HTTP requests by path and method.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (path, method), count in sorted(self._request_count.items()):
                lines.append(f'http_requests_total{{path="{path}",method="{method}"}} {count}')

            lines.extend(
                [
                    "# HELP http_request_duration_seconds_sum Total request latency in seconds by path and method.",
                    "# TYPE http_request_duration_seconds_sum counter",
                ]
            )
            for (path, method), total in sorted(self._request_latency_sum.items()):
                lines.append(
                    f'http_request_duration_seconds_sum{{path="{path}",method="{method}"}} {total:.6f}'
                )

        lines.append("")
        return "\n".join(lines)


@dataclass
class Settings:
    coordinator_url: str
    internal_token: str
    api_keys: dict[str, str]
    rate_limit_per_minute_api_key: int
    rate_limit_per_minute_ip: int
    poll_timeout_seconds: float
    poll_interval_seconds: float
    cors_enabled: bool
    cors_allow_origins: list[str]
    enable_prometheus_metrics: bool


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
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded"
                )

            bucket.append(now)


class EmbedRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class RankRequest(BaseModel):
    query: str = Field(min_length=1)
    texts: list[str] = Field(min_length=1, max_length=32)


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


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
        rate_limit_per_minute_api_key=int(
            os.getenv("RATE_LIMIT_PER_MINUTE_API_KEY", os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        ),
        rate_limit_per_minute_ip=int(os.getenv("RATE_LIMIT_PER_MINUTE_IP", "120")),
        poll_timeout_seconds=float(os.getenv("POLL_TIMEOUT_SECONDS", "20")),
        poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "1.0")),
        cors_enabled=_parse_bool(os.getenv("CORS_ENABLED"), default=False),
        cors_allow_origins=[
            origin.strip()
            for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
            if origin.strip()
        ],
        enable_prometheus_metrics=_parse_bool(
            os.getenv("ENABLE_PROMETHEUS_METRICS"), default=False
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.settings = load_settings()
    app.state.rate_limiter_api_key = RateLimiter(
        max_requests=app.state.settings.rate_limit_per_minute_api_key
    )
    app.state.rate_limiter_ip = RateLimiter(
        max_requests=app.state.settings.rate_limit_per_minute_ip
    )
    app.state.coordinator_client = httpx.AsyncClient(
        base_url=app.state.settings.coordinator_url, timeout=5.0
    )
    app.state.metrics = PrometheusMetrics(enabled=app.state.settings.enable_prometheus_metrics)
    yield
    await app.state.coordinator_client.aclose()


app = FastAPI(title="OpenMesh Pool Gateway", version="0.1.0", lifespan=lifespan)
app.state.metrics = PrometheusMetrics(enabled=False)


settings_for_cors = load_settings()
if settings_for_cors.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_for_cors.cors_allow_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _validate_rank_texts(texts: list[str]) -> None:
    for idx, text in enumerate(texts):
        if len(text) > 10_000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"texts[{idx}] exceeds max length of 10000",
            )


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

    client_ip = _client_ip(request)
    request.app.state.rate_limiter_api_key.check(x_api_key)
    request.app.state.rate_limiter_ip.check(client_ip)
    return client_id


@app.middleware("http")
async def request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})

    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.observe_http_request(
                path=request.url.path,
                method=request.method,
                elapsed_seconds=elapsed_ms / 1000,
            )
        log.info("method=%s path=%s elapsed_ms=%.2f", request.method, request.url.path, elapsed_ms)

    response.headers["X-Request-ID"] = request_id
    return response


async def _create_job(
    request: Request, client_id: str, job_type: str, payload: dict[str, Any]
) -> str:
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client

    started = time.perf_counter()
    response = await client.post(
        "/internal/jobs/create",
        headers={"Authorization": f"Bearer {settings.internal_token}", "X-Request-ID": request_id},
        json={
            "client_id": client_id,
            "job_type": job_type,
            "payload": payload,
            "request_id": request_id,
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info("coordinator_create elapsed_ms=%.2f status=%s", elapsed_ms, response.status_code)

    if response.status_code in {
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_429_TOO_MANY_REQUESTS,
    }:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient balance"
        )
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
            headers={
                "Authorization": f"Bearer {settings.internal_token}",
                "X-Request-ID": request_id,
            },
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
            headers={
                "Authorization": f"Bearer {settings.internal_token}",
                "X-Request-ID": request_id,
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("coordinator_poll elapsed_ms=%.2f status=%s", elapsed_ms, response.status_code)
        response.raise_for_status()

        job = cast(dict[str, Any], response.json())
        if job.get("status") == "verified":
            return job
        await asyncio.sleep(settings.poll_interval_seconds)

    await _cancel_job(request, job_id)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Verification timeout"
    )


async def _run_job(
    request: Request, *, client_id: str, job_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    job_id = await _create_job(request, client_id, job_type, payload)
    job = await _wait_for_verification(request, job_id)
    return {"job_id": job_id, "output": job.get("output")}


@app.post("/v1/embed")
async def embed(
    payload: EmbedRequest, request: Request, client_id: str = Depends(get_client_id)
) -> dict[str, Any]:
    return await _run_job(
        request, client_id=client_id, job_type="embed", payload=payload.model_dump()
    )


@app.post("/v1/rank")
async def rank(
    payload: RankRequest, request: Request, client_id: str = Depends(get_client_id)
) -> dict[str, Any]:
    _validate_rank_texts(payload.texts)
    return await _run_job(
        request, client_id=client_id, job_type="rank", payload=payload.model_dump()
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-gateway"}


@app.get("/metrics")
def metrics(request: Request) -> Response:
    return Response(
        content=request.app.state.metrics.render(), media_type="text/plain; version=0.0.4"
    )
