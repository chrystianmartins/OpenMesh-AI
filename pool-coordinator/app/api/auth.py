from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.accounting import Account
from app.db.models.auth import ApiKey, User
from app.db.models.enums import OwnerType, Role
from app.db.session import SessionLocal
from app.schemas.auth import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
password_hasher = PasswordHasher()
ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 86400 * 14


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _token_secret() -> str:
    settings = get_settings()
    return settings.admin_password


def _encode_token(payload: dict[str, Any], expires_in_seconds: int) -> tuple[str, int]:
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    token = jwt.encode({**payload, "exp": expires_at}, _token_secret(), algorithm="HS256")
    return token, expires_in_seconds


def _build_tokens(user: User) -> TokenResponse:
    common_payload = {"sub": str(user.id), "email": user.email, "role": user.role.value}
    access_token, access_expires = _encode_token({**common_payload, "type": "access"}, ACCESS_TOKEN_TTL_SECONDS)
    refresh_token, _ = _encode_token({**common_payload, "type": "refresh"}, REFRESH_TOKEN_TTL_SECONDS)
    return TokenResponse(
        access_token=access_token,
        expires_in=access_expires,
        refresh_token=refresh_token,
    )


def _parse_user_id(token: str) -> int:
    try:
        payload = jwt.decode(token, _token_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    try:
        return int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload") from exc


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user_id = _parse_user_id(token)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not available")
    return user


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
        password_hash=password_hasher.hash(payload.password),
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

    try:
        is_valid = password_hasher.verify(user.password_hash, payload.password)
    except VerifyMismatchError:
        is_valid = False

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return _build_tokens(user)


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiKeyResponse:
    if current_user.role != Role.CLIENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only clients can create API keys")

    raw_key = f"omk_{secrets.token_urlsafe(32)}"
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_row = ApiKey(user_id=current_user.id, name=payload.name, key_hash=hashed_key, revoked=False)

    db.add(key_row)
    db.commit()
    db.refresh(key_row)

    return ApiKeyResponse(id=key_row.id, name=key_row.name, key=raw_key, created_at=key_row.created_at)
