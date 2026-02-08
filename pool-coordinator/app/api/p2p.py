from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hmac import compare_digest

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import get_db
from app.db.models.enums import AssignmentStatus, JobStatus, WorkerStatus
from app.db.models.jobs import Assignment, Job
from app.db.models.p2p import Peer
from app.db.models.workers import Worker
from app.schemas.p2p import (
    P2PJobForwardRequest,
    P2PJobForwardResponse,
    P2PPeerRegisterRequest,
    P2PPeerRegisterResponse,
    P2PResultRelayRequest,
    P2PResultRelayResponse,
)
from app.services.finance import record_interpool_fee_placeholder
from app.services.job_dispatcher import create_queued_job

router = APIRouter(prefix="/p2p", tags=["p2p"])


def _authenticate_peer(db: Session, *, peer_id: str, shared_secret: str) -> Peer:
    peer = db.scalar(select(Peer).where(Peer.peer_id == peer_id))
    if peer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Peer is not allowlisted")
    if not compare_digest(peer.shared_secret, shared_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid shared secret")
    return peer


def _has_available_capacity(db: Session) -> bool:
    workers = db.scalars(
        select(Worker)
        .options(joinedload(Worker.settings))
        .where(Worker.status == WorkerStatus.ONLINE)
    ).all()
    if not workers:
        return False

    active_counts = {
        worker_id: count
        for worker_id, count in db.execute(
            select(Assignment.worker_id, func.count(Assignment.id))
            .where(Assignment.status.in_([AssignmentStatus.ASSIGNED, AssignmentStatus.STARTED]))
            .group_by(Assignment.worker_id)
        ).all()
        if worker_id is not None
    }

    for worker in workers:
        settings = worker.settings
        if settings is None or not settings.accept_new_assignments:
            continue
        if active_counts.get(worker.id, 0) < settings.max_concurrency:
            return True
    return False


@router.post("/peers/register", response_model=P2PPeerRegisterResponse)
def register_peer(
    payload: P2PPeerRegisterRequest,
    db: Session = Depends(get_db),
) -> P2PPeerRegisterResponse:
    peer = _authenticate_peer(db, peer_id=payload.peer_id, shared_secret=payload.shared_secret)

    now = datetime.now(UTC)
    peer.url = payload.url
    peer.last_seen = now
    db.commit()

    return P2PPeerRegisterResponse(peer_id=peer.peer_id, url=peer.url, last_seen=now)


@router.post("/jobs/forward", response_model=P2PJobForwardResponse)
def forward_job(
    payload: P2PJobForwardRequest,
    db: Session = Depends(get_db),
) -> P2PJobForwardResponse:
    peer = _authenticate_peer(db, peer_id=payload.peer_id, shared_secret=payload.shared_secret)

    if not _has_available_capacity(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local pool has no capacity")

    job_payload = dict(payload.payload)
    job_payload["federation"] = {
        "origin_pool": payload.origin_pool,
        "origin_job_id": payload.origin_job_id,
        "forwarded_by": payload.peer_id,
    }

    job, _ = create_queued_job(
        db,
        created_by_user_id=None,
        payload=job_payload,
        job_type=payload.job_type,
        priority=payload.priority,
        price_multiplier=Decimal("1.0"),
    )
    peer.last_seen = datetime.now(UTC)
    record_interpool_fee_placeholder(
        db,
        job_id=job.id,
        peer_id=peer.peer_id,
        direction="inbound_forward",
        details={"origin_job_id": payload.origin_job_id},
    )
    db.commit()

    return P2PJobForwardResponse(accepted=True, local_job_id=job.id, status=job.status.value)


@router.post("/results/relay", response_model=P2PResultRelayResponse)
def relay_result(
    payload: P2PResultRelayRequest,
    db: Session = Depends(get_db),
) -> P2PResultRelayResponse:
    peer = _authenticate_peer(db, peer_id=payload.peer_id, shared_secret=payload.shared_secret)

    job = db.get(Job, payload.local_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local job not found")

    job_payload = dict(job.payload)
    job_payload["relayed_result"] = {
        "from_peer": payload.peer_id,
        "output": payload.output,
        "error_message": payload.error_message,
        "output_hash": payload.output_hash,
        "relayed_at": datetime.now(UTC).isoformat(),
    }
    job.payload = job_payload
    job.status = JobStatus.COMPLETED if payload.error_message is None else JobStatus.FAILED

    peer.last_seen = datetime.now(UTC)
    record_interpool_fee_placeholder(
        db,
        job_id=job.id,
        peer_id=peer.peer_id,
        direction="result_relay",
    )
    db.commit()
    return P2PResultRelayResponse(accepted=True, local_job_id=job.id, status=job.status.value)
