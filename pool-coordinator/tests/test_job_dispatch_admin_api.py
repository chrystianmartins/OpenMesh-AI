from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.accounting import Account, LedgerEntry
from app.db.models.enums import AssignmentStatus, JobStatus, JobType, OwnerType, Role, WorkerStatus
from app.db.models.jobs import Assignment, Job
from app.db.models.workers import Worker, WorkerHeartbeat, WorkerSettings
from app.services.job_dispatcher import assign_queued_jobs


def test_internal_create_job_creates_queued_with_estimated_units(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/internal/jobs/create",
        json={
            "job_type": "inference",
            "payload": {"prompt": "x" * 1500},
            "priority": 5,
            "price_multiplier": "1.0",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["estimated_units"] == 2

    job = db_session.get(Job, body["job_id"])
    assert job is not None
    assert job.status == JobStatus.QUEUED


def test_assign_queued_jobs_prioritizes_reputation_then_latency_and_parallelism(db_session: Session) -> None:
    worker_a = Worker(
        name="worker-a",
        owner_user_id=1,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 0.9, "estimated_latency_ms": 100, "price_multiplier": 1.0},
    )
    worker_b = Worker(
        name="worker-b",
        owner_user_id=1,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 0.9, "estimated_latency_ms": 50, "price_multiplier": 1.0},
    )
    worker_c = Worker(
        name="worker-c",
        owner_user_id=1,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 0.95, "estimated_latency_ms": 500, "price_multiplier": 2.0},
    )
    db_session.add_all([worker_a, worker_b, worker_c])
    db_session.flush()

    db_session.add_all(
        [
            WorkerSettings(worker_id=worker_a.id, max_concurrency=1, accept_new_assignments=True),
            WorkerSettings(worker_id=worker_b.id, max_concurrency=2, accept_new_assignments=True),
            WorkerSettings(worker_id=worker_c.id, max_concurrency=2, accept_new_assignments=True),
        ]
    )
    job_running = Job(
        created_by_user_id=None,
        job_type=JobType.INFERENCE,
        status=JobStatus.RUNNING,
        payload={"prompt": "running", "price_multiplier": 1.0},
    )
    job_queued = Job(
        created_by_user_id=None,
        job_type=JobType.INFERENCE,
        status=JobStatus.QUEUED,
        payload={"prompt": "dispatch", "price_multiplier": 1.0},
    )
    db_session.add_all([job_running, job_queued])
    db_session.flush()

    db_session.add(
        Assignment(
            job_id=job_running.id,
            worker_id=worker_a.id,
            status=AssignmentStatus.ASSIGNED,
            assigned_at=datetime.now(UTC),
            nonce="existing-a",
        )
    )
    db_session.commit()

    assigned = assign_queued_jobs(db_session)
    db_session.commit()

    assert assigned == 1
    created_assignment = db_session.scalar(select(Assignment).where(Assignment.job_id == job_queued.id))
    assert created_assignment is not None
    assert created_assignment.worker_id == worker_b.id


def test_admin_endpoints_list_jobs_workers_and_leaderboard(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="admin-owner@test.local", role=Role.WORKER_OWNER)
    headers = auth_headers("admin-owner@test.local", "super-secret-password")

    worker = Worker(
        name="leader-worker",
        owner_user_id=owner.id,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 0.8, "estimated_latency_ms": 25},
    )
    db_session.add(worker)
    db_session.flush()
    db_session.add(WorkerSettings(worker_id=worker.id, max_concurrency=3, accept_new_assignments=True))

    job = Job(created_by_user_id=owner.id, job_type=JobType.INFERENCE, status=JobStatus.QUEUED, payload={"prompt": "a"})
    db_session.add(job)
    db_session.flush()

    assignment = Assignment(
        job_id=job.id,
        worker_id=worker.id,
        status=AssignmentStatus.COMPLETED,
        assigned_at=datetime.now(UTC),
        nonce="leader-1",
    )
    db_session.add(assignment)
    db_session.flush()

    account = Account(owner_type=OwnerType.USER, owner_id=owner.id, currency="TOK", balance=Decimal("0"))
    db_session.add(account)
    db_session.flush()

    db_session.add(
        LedgerEntry(
            account_id=account.id,
            job_id=job.id,
            assignment_id=assignment.id,
            amount=Decimal("12.5"),
            entry_type="worker_reward",
        )
    )
    db_session.commit()

    enqueue = client.post("/admin/jobs/enqueue-demo", json={"count": 2}, headers=headers)
    assert enqueue.status_code == 201
    assert enqueue.json()["enqueued"] == 2

    jobs_response = client.get("/admin/jobs?status=queued", headers=headers)
    assert jobs_response.status_code == 200
    assert len(jobs_response.json()["jobs"]) >= 1

    workers_response = client.get("/admin/workers", headers=headers)
    assert workers_response.status_code == 200
    assert workers_response.json()["workers"][0]["name"] == "leader-worker"

    leaderboard_response = client.get("/admin/leaderboard", headers=headers)
    assert leaderboard_response.status_code == 200
    assert leaderboard_response.json()["leaderboard"][0]["tokens_earned"] == "12.50000000"


def test_daily_emission_partial_uptime_receives_proportional_tokens(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "daily_emission_base_tokens", 24.0)
    monkeypatch.setattr(settings, "daily_emission_cap_tokens", 100.0)

    owner = create_user(email="emission-owner@test.local", role=Role.WORKER_OWNER)
    headers = auth_headers("emission-owner@test.local", "super-secret-password")

    worker = Worker(
        name="emission-worker",
        owner_user_id=owner.id,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 1.0},
    )
    db_session.add(worker)
    db_session.flush()
    db_session.add(WorkerSettings(worker_id=worker.id, heartbeat_timeout_seconds=3600, accept_new_assignments=True))

    now = datetime.now(UTC)
    db_session.add(WorkerHeartbeat(worker_id=worker.id, recorded_at=now - timedelta(hours=12)))
    db_session.commit()

    run_response = client.post("/admin/emission/run-now", headers=headers)
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["workers_rewarded"] == 1
    emitted = Decimal(payload["emitted_tokens"])
    assert Decimal("0.99") <= emitted <= Decimal("1.01")

    emission_entry = db_session.scalar(select(LedgerEntry).where(LedgerEntry.entry_type == "daily_emission"))
    assert emission_entry is not None
    assert emission_entry.details is not None
    assert emission_entry.details["reason"] == "daily_emission"

    status_response = client.get("/admin/emission/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["run_completed"] is True


def test_daily_emission_respects_daily_cap(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "daily_emission_base_tokens", 24.0)
    monkeypatch.setattr(settings, "daily_emission_cap_tokens", 3.0)

    owner_a = create_user(email="emission-a@test.local", role=Role.WORKER_OWNER)
    owner_b = create_user(email="emission-b@test.local", role=Role.WORKER_OWNER)
    headers = auth_headers("emission-a@test.local", "super-secret-password")

    worker_a = Worker(
        name="cap-worker-a",
        owner_user_id=owner_a.id,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 1.0},
    )
    worker_b = Worker(
        name="cap-worker-b",
        owner_user_id=owner_b.id,
        status=WorkerStatus.ONLINE,
        specs_json={"reputation": 1.0},
    )
    db_session.add_all([worker_a, worker_b])
    db_session.flush()
    db_session.add_all(
        [
            WorkerSettings(worker_id=worker_a.id, heartbeat_timeout_seconds=86400, accept_new_assignments=True),
            WorkerSettings(worker_id=worker_b.id, heartbeat_timeout_seconds=86400, accept_new_assignments=True),
        ]
    )

    now = datetime.now(UTC)
    db_session.add_all(
        [
            WorkerHeartbeat(worker_id=worker_a.id, recorded_at=now - timedelta(hours=24)),
            WorkerHeartbeat(worker_id=worker_b.id, recorded_at=now - timedelta(hours=24)),
        ]
    )
    db_session.commit()

    run_response = client.post("/admin/emission/run-now", headers=headers)
    assert run_response.status_code == 200
    assert run_response.json()["emitted_tokens"] == "3.00000000"

    status_response = client.get("/admin/emission/status", headers=headers)
    assert status_response.status_code == 200
    assert Decimal(status_response.json()["remaining_tokens"]) == Decimal("0")
