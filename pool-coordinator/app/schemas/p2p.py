from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import JobType


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeerAuthMixin(StrictBaseModel):
    peer_id: str = Field(min_length=3, max_length=64)
    shared_secret: str = Field(min_length=8, max_length=255)


class P2PPeerRegisterRequest(PeerAuthMixin):
    url: str = Field(min_length=1, max_length=512)


class P2PPeerRegisterResponse(BaseModel):
    peer_id: str
    url: str
    last_seen: datetime


class P2PJobForwardRequest(PeerAuthMixin):
    origin_job_id: str = Field(min_length=1, max_length=128)
    origin_pool: str = Field(min_length=1, max_length=128)
    job_type: JobType
    payload: dict[str, Any]
    priority: int = Field(default=0, ge=0, le=100)


class P2PJobForwardResponse(BaseModel):
    accepted: bool
    local_job_id: int
    status: str


class P2PResultRelayRequest(PeerAuthMixin):
    local_job_id: int = Field(gt=0)
    output: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=2000)
    output_hash: str | None = Field(default=None, max_length=128)


class P2PResultRelayResponse(BaseModel):
    accepted: bool
    local_job_id: int
    status: str
