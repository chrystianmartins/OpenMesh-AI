from __future__ import annotations

import base64
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import get_db, require_roles
from app.db.models.auth import User
from app.db.models.enums import AssignmentStatus, Role, WorkerStatus
from app.db.models.jobs import Assignment, Result
from app.db.models.workers import Worker
from app.schemas.jobs import JobPollRequest, JobPollResponse, JobSubmitRequest, JobSubmitResponse
from app.schemas.workers import WorkerHeartbeatRequest, WorkerHeartbeatResponse

router = APIRouter(tags=["jobs"])


def _is_valid_base64url(value: str) -> bool:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        return False
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(f"{value}{padding}")
    except (ValueError, TypeError):
        return False
    return len(decoded) > 0


def _get_owned_worker(*, db: Session, worker_id: int, owner_user_id: int) -> Worker:
    worker = db.scalar(select(Worker).where(Worker.id == worker_id, Worker.owner_user_id == owner_user_id))
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    return worker


@router.post("/workers/heartbeat", response_model=WorkerHeartbeatResponse)
def heartbeat_worker(
    payload: WorkerHeartbeatRequest,
    current_user: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> WorkerHeartbeatResponse:
    worker = _get_owned_worker(db=db, worker_id=payload.worker_id, owner_user_id=current_user.id)
    now = datetime.now(UTC)
    worker.last_seen_at = now
    worker.status = WorkerStatus.ONLINE
    db.commit()
    return WorkerHeartbeatResponse(worker_id=worker.id, last_seen_at=now)


@router.post("/jobs/poll", response_model=JobPollResponse)
def poll_job(
    payload: JobPollRequest,
    current_user: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> JobPollResponse:
    worker = _get_owned_worker(db=db, worker_id=payload.worker_id, owner_user_id=current_user.id)

    assignment = db.scalar(
        select(Assignment)
        .options(joinedload(Assignment.job))
        .where(
            Assignment.worker_id == worker.id,
            Assignment.status == AssignmentStatus.PENDING,
        )
        .order_by(Assignment.assigned_at.asc())
    )
    if assignment is None or assignment.job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No assignment available")

    return JobPollResponse(
        assignment_id=assignment.id,
        job=assignment.job.payload,
        nonce=assignment.nonce,
        cost_hint_tokens=assignment.job.priority,
    )


@router.post("/jobs/submit", response_model=JobSubmitResponse)
def submit_job(
    payload: JobSubmitRequest,
    current_user: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    worker = _get_owned_worker(db=db, worker_id=payload.worker_id, owner_user_id=current_user.id)

    assignment = db.scalar(
        select(Assignment)
        .options(joinedload(Assignment.result))
        .where(Assignment.id == payload.assignment_id, Assignment.worker_id == worker.id)
    )
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.nonce != payload.nonce:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid nonce")

    if assignment.result is not None or assignment.status in {
        AssignmentStatus.COMPLETED,
        AssignmentStatus.FAILED,
        AssignmentStatus.CANCELED,
    }:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Assignment already submitted")

    if not _is_valid_base64url(payload.signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    finished_at = datetime.now(UTC)
    assignment.status = AssignmentStatus.COMPLETED if payload.error_message is None else AssignmentStatus.FAILED
    assignment.finished_at = finished_at

    db.add(
        Result(
            assignment_id=assignment.id,
            output=payload.output,
            error_message=payload.error_message,
            artifact_uri=payload.artifact_uri,
            output_hash=payload.output_hash,
            signature=payload.signature,
            metrics_json=payload.metrics_json,
        )
    )
    db.commit()

    return JobSubmitResponse(
        assignment_id=assignment.id,
        status=assignment.status.value,
        finished_at=finished_at,
    )
