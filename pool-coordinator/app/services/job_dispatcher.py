from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models.enums import AssignmentStatus, JobStatus, WorkerStatus
from app.db.models.jobs import Assignment, Job
from app.db.models.workers import Worker
from app.services.finance import estimate_payload_units

DEFAULT_PRICE_MULTIPLIER = Decimal("1.0")
DEFAULT_REPUTATION = Decimal("0.5")
DEFAULT_ESTIMATED_LATENCY_MS = 1_000_000


def create_queued_job(
    db: Session,
    *,
    created_by_user_id: int | None,
    payload: dict[str, object],
    job_type: object,
    priority: int,
    price_multiplier: Decimal,
) -> tuple[Job, int]:
    estimated_units = estimate_payload_units(payload)
    job_payload = dict(payload)
    job_payload.setdefault("price_multiplier", float(price_multiplier))

    job = Job(
        created_by_user_id=created_by_user_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        payload=job_payload,
        priority=priority,
    )
    db.add(job)
    db.flush()
    return job, estimated_units


def _worker_decimal_setting(worker: Worker, key: str, default: Decimal) -> Decimal:
    specs = worker.specs_json if isinstance(worker.specs_json, dict) else {}
    value = specs.get(key)
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except ArithmeticError:
            return default
    return default


def _worker_latency_ms(worker: Worker) -> int:
    specs = worker.specs_json if isinstance(worker.specs_json, dict) else {}
    latency = specs.get("estimated_latency_ms")
    if isinstance(latency, int) and latency >= 0:
        return latency
    return DEFAULT_ESTIMATED_LATENCY_MS


def _job_price_multiplier(job: Job) -> Decimal:
    raw_value = job.payload.get("price_multiplier") if isinstance(job.payload, dict) else None
    if isinstance(raw_value, (int, float, str)):
        try:
            return Decimal(str(raw_value))
        except ArithmeticError:
            return DEFAULT_PRICE_MULTIPLIER
    return DEFAULT_PRICE_MULTIPLIER


def assign_queued_jobs(db: Session, *, limit: int = 50) -> int:
    queued_jobs = db.scalars(
        select(Job)
        .where(Job.status == JobStatus.QUEUED)
        .order_by(Job.priority.desc(), Job.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    if not queued_jobs:
        return 0

    workers = db.scalars(
        select(Worker)
        .options(joinedload(Worker.settings))
        .where(Worker.status == WorkerStatus.ONLINE)
    ).all()
    if not workers:
        return 0

    active_counts = {
        worker_id: count
        for worker_id, count in db.execute(
            select(Assignment.worker_id, func.count(Assignment.id))
            .where(Assignment.status.in_([AssignmentStatus.ASSIGNED, AssignmentStatus.STARTED]))
            .group_by(Assignment.worker_id)
        ).all()
        if worker_id is not None
    }

    assigned_count = 0
    now = datetime.now(UTC)
    for job in queued_jobs:
        job_price = _job_price_multiplier(job)

        candidates: list[tuple[Decimal, int, int, Worker]] = []
        for worker in workers:
            settings = worker.settings
            if settings is None:
                continue
            if not settings.accept_new_assignments:
                continue

            max_parallel_jobs = settings.max_concurrency
            current_parallel_jobs = active_counts.get(worker.id, 0)
            if current_parallel_jobs >= max_parallel_jobs:
                continue

            worker_price = _worker_decimal_setting(worker, "price_multiplier", DEFAULT_PRICE_MULTIPLIER)
            if worker_price > job_price:
                continue

            worker_reputation = _worker_decimal_setting(worker, "reputation", DEFAULT_REPUTATION)
            worker_latency_ms = _worker_latency_ms(worker)
            candidates.append((worker_reputation, worker_latency_ms, current_parallel_jobs, worker))

        if not candidates:
            continue

        candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3].id))
        selected_worker = candidates[0][3]

        db.add(
            Assignment(
                job_id=job.id,
                worker_id=selected_worker.id,
                status=AssignmentStatus.ASSIGNED,
                assigned_at=now,
                nonce=f"job-{job.id}-{uuid4().hex}",
            )
        )
        job.status = JobStatus.RUNNING
        active_counts[selected_worker.id] = active_counts.get(selected_worker.id, 0) + 1
        assigned_count += 1

    if assigned_count > 0:
        db.flush()

    return assigned_count
