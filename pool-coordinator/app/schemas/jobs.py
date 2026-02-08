from __future__ import annotations

from datetime import datetime
import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models.enums import JobType

MAX_JSON_PAYLOAD_CHARS = 200_000
MAX_ERROR_MESSAGE_CHARS = 2_000
MAX_ARTIFACT_URI_CHARS = 2_048
MAX_OUTPUT_HASH_CHARS = 128
MAX_SIGNATURE_CHARS = 512
MAX_METRICS_KEYS = 64


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobPollRequest(StrictBaseModel):
    worker_id: int


class JobPollResponse(BaseModel):
    assignment_id: int
    job: dict[str, Any]
    nonce: str
    cost_hint_tokens: int


class JobSubmitRequest(StrictBaseModel):
    worker_id: int
    assignment_id: int
    nonce: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=1, max_length=MAX_SIGNATURE_CHARS)
    output: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=MAX_ERROR_MESSAGE_CHARS)
    artifact_uri: str | None = Field(default=None, max_length=MAX_ARTIFACT_URI_CHARS)
    output_hash: str | None = Field(default=None, max_length=MAX_OUTPUT_HASH_CHARS)
    metrics_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_submission(self) -> JobSubmitRequest:
        if self.output is None and self.error_message is None:
            raise ValueError("Either output or error_message must be provided")

        if self.output is not None and self.error_message is not None:
            raise ValueError("output and error_message are mutually exclusive")

        if self.metrics_json is not None and len(self.metrics_json) > MAX_METRICS_KEYS:
            raise ValueError(f"metrics_json supports at most {MAX_METRICS_KEYS} keys")

        if self.output is not None:
            output_size = len(json.dumps(self.output, ensure_ascii=False, separators=(",", ":")))
            if output_size > MAX_JSON_PAYLOAD_CHARS:
                raise ValueError(f"output exceeds max size of {MAX_JSON_PAYLOAD_CHARS} characters")

        if self.metrics_json is not None:
            metrics_size = len(
                json.dumps(self.metrics_json, ensure_ascii=False, separators=(",", ":"))
            )
            if metrics_size > MAX_JSON_PAYLOAD_CHARS:
                raise ValueError(
                    f"metrics_json exceeds max size of {MAX_JSON_PAYLOAD_CHARS} characters"
                )

        return self


class JobSubmitResponse(BaseModel):
    assignment_id: int
    status: str
    finished_at: datetime


class InternalJobCreateRequest(StrictBaseModel):
    job_type: JobType
    payload: dict[str, Any]
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    created_by_user_id: int | None = None
    priority: int = Field(default=0, ge=0, le=100)
    price_multiplier: Decimal = Field(default=Decimal("1.0"), gt=0)


class InternalJobCreateResponse(BaseModel):
    job_id: int
    status: str
    estimated_units: int
    price_multiplier: Decimal


class AdminEnqueueDemoRequest(StrictBaseModel):
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
