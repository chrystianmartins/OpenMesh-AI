from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_db, require_roles
from app.db.models.auth import User
from app.db.models.enums import Role, WorkerStatus
from app.db.models.workers import Worker
from app.schemas.workers import WorkerListResponse, WorkerRegisterRequest, WorkerResponse

router = APIRouter(tags=["workers"])


@router.post("/workers/register", response_model=WorkerResponse, status_code=status.HTTP_201_CREATED)
def register_worker(
    payload: WorkerRegisterRequest,
    current_user: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> WorkerResponse:
    worker = Worker(
        name=payload.name,
        owner_user_id=current_user.id,
        region=payload.region,
        specs_json=payload.specs_json,
        public_key=payload.public_key,
        status=WorkerStatus.OFFLINE,
    )
    db.add(worker)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Worker name already exists") from exc

    db.refresh(worker)
    return WorkerResponse.model_validate(worker)


@router.get("/workers", response_model=WorkerListResponse)
def list_workers(
    current_user: User = Depends(require_roles(Role.WORKER_OWNER)),
    db: Session = Depends(get_db),
) -> WorkerListResponse:
    workers = db.scalars(select(Worker).where(Worker.owner_user_id == current_user.id).order_by(Worker.id.asc())).all()
    return WorkerListResponse(workers=[WorkerResponse.model_validate(worker) for worker in workers])
