from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import get_db, require_roles
from app.core.protocol_crypto import ProtocolCryptoError, canonical_json, verify_ed25519_signature
from app.db.models.auth import User
from app.db.models.enums import AssignmentStatus, JobStatus, Role, WorkerStatus
from app.db.models.jobs import Assignment, Result
from app.db.models.workers import Worker, WorkerHeartbeat
from app.schemas.jobs import (
    InternalJobCreateRequest,
    InternalJobCreateResponse,
    JobPollRequest,
    JobPollResponse,
    JobSubmitRequest,
    JobSubmitResponse,
)
from app.schemas.workers import WorkerHeartbeatRequest, WorkerHeartbeatResponse
from app.services.finance import apply_job_verification_accounting
from app.services.job_dispatcher import create_queued_job
from app.services.verification import process_submission_verification

router = APIRouter(tags=["jobs"])


def _get_owned_worker(*, db: Session, worker_id: int, owner_user_id: int) -> Worker:
    worker = db.scalar(
        select(Worker).where(Worker.id == worker_id, Worker.owner_user_id == owner_user_id)
    )
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    return worker


@router.post(
    "/internal/jobs/create",
    response_model=InternalJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_internal_job(
    payload: InternalJobCreateRequest,
    db: Session = Depends(get_db),
) -> InternalJobCreateResponse:
    job_payload = dict(payload.payload)
    if payload.request_id:
        job_payload.setdefault("request_id", payload.request_id)

    job, estimated_units = create_queued_job(
        db,
        created_by_user_id=payload.created_by_user_id,
        payload=job_payload,
        job_type=payload.job_type,
        priority=payload.priority,
        price_multiplier=payload.price_multiplier,
    )
    db.commit()
    return InternalJobCreateResponse(
        job_id=job.id,
        status=JobStatus.QUEUED.value,
        estimated_units=estimated_units,
        price_multiplier=payload.price_multiplier,
    )


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
    db.add(WorkerHeartbeat(worker_id=worker.id, recorded_at=now))
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
            Assignment.status == AssignmentStatus.ASSIGNED,
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
    request: Request,
    current_user: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    worker = _get_owned_worker(db=db, worker_id=payload.worker_id, owner_user_id=current_user.id)

    limiter = request.app.state.submit_rate_limiter
    if not limiter.allow(str(worker.id)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Submit rate limit exceeded"
        )

    if not worker.public_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Worker public key is not configured"
        )

    signed_payload = {
        "assignment_id": payload.assignment_id,
        "nonce": payload.nonce,
        "output_hash": payload.output_hash,
    }
    signed_payload_bytes = canonical_json(signed_payload)

    try:
        signature_valid = verify_ed25519_signature(
            public_key_b64url=worker.public_key,
            signature_b64url=payload.signature,
            message=signed_payload_bytes,
        )
    except ProtocolCryptoError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not signature_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Signature verification failed"
        )

    assignment = db.scalar(
        select(Assignment)
        .options(
            joinedload(Assignment.result), joinedload(Assignment.job), joinedload(Assignment.worker)
        )
        .where(Assignment.id == payload.assignment_id, Assignment.worker_id == worker.id)
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.nonce != payload.nonce:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid nonce")

    if assignment.result is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Assignment already submitted"
        )

    if assignment.status not in {AssignmentStatus.ASSIGNED, AssignmentStatus.STARTED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Assignment is not in a submittable state"
        )

    finished_at = datetime.now(UTC)
    assignment.status = (
        AssignmentStatus.COMPLETED if payload.error_message is None else AssignmentStatus.FAILED
    )
    assignment.finished_at = finished_at

    result = Result(
        assignment_id=assignment.id,
        output=payload.output,
        error_message=payload.error_message,
        artifact_uri=payload.artifact_uri,
        output_hash=payload.output_hash,
        signature=payload.signature,
        metrics_json=payload.metrics_json,
    )
    db.add(result)

    process_submission_verification(db, assignment, result)
    apply_job_verification_accounting(db, assignment=assignment, result=result)

    try:
        db.commit()
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Concurrent submission conflict"
        ) from exc

    return JobSubmitResponse(
        assignment_id=assignment.id,
        status=assignment.status.value,
        finished_at=finished_at,
    )
