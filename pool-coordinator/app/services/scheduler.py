from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import SessionLocal
from app.services.job_dispatcher import assign_queued_jobs

logger = logging.getLogger(__name__)


async def _dispatch_loop(stop_event: asyncio.Event, *, interval_seconds: float = 2.0) -> None:
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                assigned = assign_queued_jobs(db)
                if assigned > 0:
                    db.commit()
                else:
                    db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("job scheduler loop failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def scheduler_lifespan(app: FastAPI) -> AsyncIterator[None]:
    stop_event = asyncio.Event()
    task = asyncio.create_task(_dispatch_loop(stop_event))
    app.state.dispatcher_stop_event = stop_event
    app.state.dispatcher_task = task
    try:
        yield
    finally:
        stop_event.set()
        await task
