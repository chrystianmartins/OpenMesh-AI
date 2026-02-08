from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.db.models.enums import JobType


class JobPollRequest(BaseModel):
    worker_id: int


class JobPollResponse(BaseModel):
    assignment_id: int
    job: dict[str, Any]
    nonce: str
    cost_hint_tokens: int


class JobSubmitRequest(BaseModel):
    worker_id: int
    assignment_id: int
    nonce: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=1)
    output: dict[str, Any] | None = None
    error_message: str | None = None
    artifact_uri: str | None = None
    output_hash: str | None = Field(default=None, max_length=128)
    metrics_json: dict[str, Any] | None = None


class JobSubmitResponse(BaseModel):
    assignment_id: int
    status: str
    finished_at: datetime


class InternalJobCreateRequest(BaseModel):
    job_type: JobType
    payload: dict[str, Any]
    created_by_user_id: int | None = None
    priority: int = Field(default=0, ge=0, le=100)
    price_multiplier: Decimal = Field(default=Decimal("1.0"), gt=0)


class InternalJobCreateResponse(BaseModel):
    job_id: int
    status: str
    estimated_units: int
    price_multiplier: Decimal


class AdminEnqueueDemoRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=500)
    job_type: JobType = JobType.INFERENCE
    priority: int = Field(default=0, ge=0, le=100)


class JobAdminItem(BaseModel):
    id: int
    job_type: JobType
    status: str
    priority: int
    created_by_user_id: int | None
    created_at: datetime


class AdminJobsResponse(BaseModel):
    jobs: list[JobAdminItem]
