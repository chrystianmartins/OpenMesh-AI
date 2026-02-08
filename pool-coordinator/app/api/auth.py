from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_db, require_roles
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.db.models.accounting import Account
from app.db.models.auth import ApiKey, User
from app.db.models.enums import OwnerType, Role
from app.schemas.auth import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.services.api_keys import generate_api_key_material

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    existing_user = db.scalar(select(User).where(User.email == payload.email))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    role = Role.CLIENT if payload.role == "client" else Role.WORKER_OWNER

    user = User(
        email=payload.email,
        role=role,
        is_active=True,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    if role == Role.CLIENT:
        db.add(
            Account(
                owner_type=OwnerType.USER,
                owner_id=user.id,
                currency="USD",
            )
        )

    db.commit()
    db.refresh(user)
    return RegisterResponse(user_id=user.id, email=user.email, role=payload.role)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token, expires_in = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )
    refresh_token, _ = create_refresh_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
    )


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: CreateApiKeyRequest,
    current_user: User = Depends(require_roles(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApiKeyResponse:
    key_material = generate_api_key_material()
    key_row = ApiKey(
        user_id=current_user.id,
        name=payload.name,
        prefix=key_material.prefix,
        key_hash=key_material.key_hash,
        revoked=False,
    )

    db.add(key_row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "API key creation conflict",
            extra={"user_id": current_user.id, "key_name": payload.name},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to create API key. Please retry.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "Database error while creating API key",
            extra={"user_id": current_user.id, "key_name": payload.name},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create API key.",
        ) from exc

    db.refresh(key_row)

    return ApiKeyResponse(
        id=key_row.id,
        name=key_row.name,
        prefix=key_row.prefix,
        key=key_material.raw_key,
        created_at=key_row.created_at,
    )
