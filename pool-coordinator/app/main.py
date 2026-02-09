from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.me import router as me_router
from app.api.p2p import router as p2p_router
from app.api.workers import router as workers_router
from app.core.logging import configure_logging
from app.core.observability import PrometheusMetrics
from app.core.rate_limit import SlidingWindowRateLimiter
from app.services.scheduler import scheduler_lifespan

configure_logging()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000

        response.headers["X-Request-ID"] = request_id
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.observe_http_request(
                path=request.url.path,
                method=request.method,
                elapsed_seconds=elapsed_ms / 1000,
            )
        app_logger = getattr(request.app.state, "logger", None)
        if app_logger is not None:
            app_logger.info(
                "method=%s path=%s status=%s elapsed_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                extra={"request_id": request_id},
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.submit_rate_limiter = SlidingWindowRateLimiter(
        max_requests=int(os.getenv("SUBMIT_RATE_LIMIT_PER_MINUTE", "60")),
    )
    app.state.metrics = PrometheusMetrics.from_env()
    async with scheduler_lifespan(app):
        yield


app = FastAPI(title="OpenMesh Pool Coordinator", version="0.1.0", lifespan=lifespan)
app.state.logger = logging.getLogger("pool-coordinator")
app.state.metrics = PrometheusMetrics(enabled=False)
app.add_middleware(RequestContextMiddleware)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(me_router)
app.include_router(workers_router)
app.include_router(jobs_router)
app.include_router(p2p_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-coordinator"}


@app.get("/metrics")
def metrics(request: Request) -> Response:
    body = request.app.state.metrics.render()
    return Response(content=body, media_type="text/plain; version=0.0.4")
