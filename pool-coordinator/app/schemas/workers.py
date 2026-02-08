from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkerRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=64)
    specs_json: dict[str, Any] | None = None
    public_key: str | None = Field(default=None, max_length=1024)


class WorkerResponse(BaseModel):
    id: int
    name: str
    owner_user_id: int
    status: str
    region: str | None
    specs_json: dict[str, Any] | None
    public_key: str | None
    last_seen_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class WorkerListResponse(BaseModel):
    workers: list[WorkerResponse]


class WorkerHeartbeatRequest(BaseModel):
    worker_id: int


class WorkerHeartbeatResponse(BaseModel):
    worker_id: int
    last_seen_at: datetime


class AdminWorkerItem(BaseModel):
    id: int
    name: str
    owner_user_id: int
    status: str
    reputation: Decimal
    estimated_latency_ms: int
    active_jobs: int
    max_parallel_jobs: int


class AdminWorkersResponse(BaseModel):
    workers: list[AdminWorkerItem]


class LeaderboardItem(BaseModel):
    worker_id: int
    worker_name: str
    owner_user_id: int
    tokens_earned: Decimal


class LeaderboardResponse(BaseModel):
    leaderboard: list[LeaderboardItem]
