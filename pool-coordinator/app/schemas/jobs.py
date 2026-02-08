from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
