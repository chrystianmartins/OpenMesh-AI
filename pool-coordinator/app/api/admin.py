from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import get_db, require_roles
from app.db.models.accounting import LedgerEntry
from app.db.models.auth import User
from app.db.models.enums import AssignmentStatus, JobStatus, Role
from app.db.models.jobs import Assignment, Job
from app.db.models.workers import Worker, WorkerSettings
from app.schemas.admin import AdminEmissionRunResponse, AdminEmissionStatusResponse
from app.schemas.jobs import AdminEnqueueDemoRequest, AdminJobsResponse, JobAdminItem
from app.schemas.me import AdminFinanceSummaryResponse
from app.schemas.workers import AdminWorkerItem, AdminWorkersResponse, LeaderboardItem, LeaderboardResponse
from app.services.emission import get_daily_emission_status, run_daily_emission
from app.services.finance import get_finance_summary
from app.services.job_dispatcher import create_queued_job

router = APIRouter(tags=["admin"])


@router.get("/admin/finance/summary", response_model=AdminFinanceSummaryResponse)
def admin_finance_summary(
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> AdminFinanceSummaryResponse:
    summary = get_finance_summary(db)
    return AdminFinanceSummaryResponse(
        total_accounts=summary.total_accounts,
        total_ledger_entries=summary.total_ledger_entries,
        total_volume_tokens=summary.total_volume_tokens,
        pool_balance_tokens=summary.pool_balance_tokens,
    )


@router.post("/admin/jobs/enqueue-demo", status_code=status.HTTP_201_CREATED)
def enqueue_demo_jobs(
    payload: AdminEnqueueDemoRequest,
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    for index in range(payload.count):
        create_queued_job(
            db,
            created_by_user_id=None,
            payload={"prompt": f"demo-job-{index + 1}", "price_multiplier": 1.0},
            job_type=payload.job_type,
            priority=payload.priority,
            price_multiplier=Decimal("1.0"),
        )
    db.commit()
    return {"enqueued": payload.count}


@router.get("/admin/jobs", response_model=AdminJobsResponse)
def list_jobs_admin(
    status: JobStatus | None = Query(default=None),
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> AdminJobsResponse:
    query = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(200)
    if status is not None:
        query = query.where(Job.status == status)

    jobs = db.scalars(query).all()
    return AdminJobsResponse(
        jobs=[
            JobAdminItem(
                id=job.id,
                job_type=job.job_type,
                status=job.status.value,
                priority=job.priority,
                created_by_user_id=job.created_by_user_id,
                created_at=job.created_at,
            )
            for job in jobs
        ]
    )


@router.get("/admin/workers", response_model=AdminWorkersResponse)
def list_workers_admin(
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> AdminWorkersResponse:
    workers = db.scalars(select(Worker).options(joinedload(Worker.settings)).order_by(Worker.id.asc())).all()
    active_counts = {
        worker_id: count
        for worker_id, count in db.execute(
            select(Assignment.worker_id, func.count(Assignment.id))
            .where(Assignment.status.in_([AssignmentStatus.ASSIGNED, AssignmentStatus.STARTED]))
            .group_by(Assignment.worker_id)
        ).all()
        if worker_id is not None
    }

    return AdminWorkersResponse(
        workers=[
            AdminWorkerItem(
                id=worker.id,
                name=worker.name,
                owner_user_id=worker.owner_user_id,
                status=worker.status.value,
                reputation=Decimal(str((worker.specs_json or {}).get("reputation", 0.5))),
                estimated_latency_ms=int((worker.specs_json or {}).get("estimated_latency_ms", 0) or 0),
                active_jobs=active_counts.get(worker.id, 0),
                max_parallel_jobs=worker.settings.max_concurrency if isinstance(worker.settings, WorkerSettings) else 1,
            )
            for worker in workers
        ]
    )


@router.get("/admin/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> LeaderboardResponse:
    rows = db.execute(
        select(
            Worker.id,
            Worker.name,
            Worker.owner_user_id,
            func.coalesce(func.sum(LedgerEntry.amount), 0).label("tokens_earned"),
        )
        .select_from(Worker)
        .outerjoin(
            Assignment,
            Assignment.worker_id == Worker.id,
        )
        .outerjoin(
            LedgerEntry,
            (LedgerEntry.assignment_id == Assignment.id) & (LedgerEntry.entry_type == "worker_reward"),
        )
        .group_by(Worker.id, Worker.name, Worker.owner_user_id)
        .order_by(func.coalesce(func.sum(LedgerEntry.amount), 0).desc(), Worker.id.asc())
    ).all()

    return LeaderboardResponse(
        leaderboard=[
            LeaderboardItem(
                worker_id=row[0],
                worker_name=row[1],
                owner_user_id=row[2],
                tokens_earned=Decimal(str(row[3])),
            )
            for row in rows
        ]
    )


@router.get("/admin/emission/status", response_model=AdminEmissionStatusResponse)
def admin_emission_status(
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> AdminEmissionStatusResponse:
    payload = get_daily_emission_status(db)
    return AdminEmissionStatusResponse(**payload)


@router.post("/admin/emission/run-now", response_model=AdminEmissionRunResponse)
def admin_emission_run_now(
    _: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> AdminEmissionRunResponse:
    result = run_daily_emission(db)
    db.commit()
    return AdminEmissionRunResponse(
        target_day=result.target_day,
        cap_tokens=result.cap_tokens,
        emitted_tokens=result.emitted_tokens,
        workers_rewarded=result.workers_rewarded,
    )
