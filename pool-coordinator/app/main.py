from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.me import router as me_router
from app.api.workers import router as workers_router
from app.core.logging import configure_logging
from app.core.rate_limit import SlidingWindowRateLimiter
from app.services.scheduler import scheduler_lifespan

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.submit_rate_limiter = SlidingWindowRateLimiter(
        max_requests=int(os.getenv("SUBMIT_RATE_LIMIT_PER_MINUTE", "60")),
    )
    async with scheduler_lifespan(app):
        yield


app = FastAPI(title="OpenMesh Pool Coordinator", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(me_router)
app.include_router(workers_router)
app.include_router(jobs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-coordinator"}
