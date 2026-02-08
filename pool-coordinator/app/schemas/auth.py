from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RegisterRole = Literal["client", "worker_owner"]


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    role: RegisterRole


class RegisterResponse(BaseModel):
    user_id: int
    email: str
    role: RegisterRole


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=3, max_length=80)


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
