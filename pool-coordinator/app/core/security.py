from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

password_hasher = PasswordHasher()


class TokenValidationError(ValueError):
    """Raised when a JWT is invalid, expired, or has unexpected claims."""


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _encode_token(payload: dict[str, Any], expires_at: datetime) -> str:
    settings = get_settings()
    claims = {**payload, "exp": expires_at}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    user_id: int,
    email: str,
    role: str,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    settings = get_settings()
    ttl_minutes = expires_minutes or settings.access_token_ttl_minutes
    expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
    token = _encode_token({"sub": str(user_id), "email": email, "role": role, "type": "access"}, expires_at)
    return token, int(timedelta(minutes=ttl_minutes).total_seconds())


def create_refresh_token(
    *,
    user_id: int,
    email: str,
    role: str,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    settings = get_settings()
    ttl_minutes = expires_minutes or settings.refresh_token_ttl_minutes
    expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
    token = _encode_token({"sub": str(user_id), "email": email, "role": role, "type": "refresh"}, expires_at)
    return token, int(timedelta(minutes=ttl_minutes).total_seconds())


def _validate_token(token: str, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenValidationError("Invalid token") from exc

    if payload.get("type") != expected_type:
        raise TokenValidationError("Invalid token type")

    subject = payload.get("sub")
    if subject is None:
        raise TokenValidationError("Missing token subject")

    return payload


def validate_access_token(token: str) -> dict[str, Any]:
    return _validate_token(token, expected_type="access")


def validate_refresh_token(token: str) -> dict[str, Any]:
    return _validate_token(token, expected_type="refresh")
