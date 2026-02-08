from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.emission import get_daily_emission_status, run_daily_emission
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


async def _daily_emission_loop(stop_event: asyncio.Event, *, interval_seconds: float = 60.0) -> None:
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                current_utc = datetime.now(UTC)
                should_run_time = (
                    current_utc.hour > settings.daily_emission_cron_hour_utc
                    or (
                        current_utc.hour == settings.daily_emission_cron_hour_utc
                        and current_utc.minute >= settings.daily_emission_cron_minute_utc
                    )
                )
                if should_run_time:
                    status_payload = get_daily_emission_status(db, now=current_utc)
                    if not bool(status_payload["run_completed"]):
                        run_daily_emission(db, now=current_utc)
                        db.commit()
                    else:
                        db.rollback()
                else:
                    db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("daily emission scheduler loop failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def scheduler_lifespan(app: FastAPI) -> AsyncIterator[None]:
    if os.getenv("PYTEST_CURRENT_TEST"):
        yield
        return

    stop_event = asyncio.Event()
    task = asyncio.create_task(_dispatch_loop(stop_event))
    emission_task = asyncio.create_task(_daily_emission_loop(stop_event))
    app.state.dispatcher_stop_event = stop_event
    app.state.dispatcher_task = task
    app.state.emission_task = emission_task
    try:
        yield
    finally:
        stop_event.set()
        await asyncio.gather(task, emission_task, return_exceptions=True)
