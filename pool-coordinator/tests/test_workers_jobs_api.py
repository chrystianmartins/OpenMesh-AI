from __future__ import annotations

import base64
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.protocol_crypto import canonical_json
from app.db.models.jobs import Assignment, Job, Result
from app.db.models.workers import Worker
from app.db.models.enums import AssignmentStatus, JobStatus, JobType, Role, WorkerStatus


def test_register_worker_sets_owner_to_current_user(client: TestClient, create_user, auth_headers, db_session: Session) -> None:
    owner = create_user(email="owner-workers@test.local", role=Role.WORKER_OWNER)
    headers = auth_headers("owner-workers@test.local", "super-secret-password")

    response = client.post(
        "/workers/register",
        json={"name": "worker-owner-a", "region": "sa-east-1", "public_key": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"},
        headers=headers,
    )

    assert response.status_code == 201
    worker = db_session.get(Worker, response.json()["id"])
    assert worker is not None
    assert worker.owner_user_id == owner.id


def test_list_workers_returns_only_owned_workers(client: TestClient, create_user, auth_headers, db_session: Session) -> None:
    owner_1 = create_user(email="owner-1@test.local", role=Role.WORKER_OWNER)
    owner_2 = create_user(email="owner-2@test.local", role=Role.WORKER_OWNER)
    db_session.add_all(
        [
            Worker(name="worker-owned", owner_user_id=owner_1.id, status=WorkerStatus.OFFLINE),
            Worker(name="worker-foreign", owner_user_id=owner_2.id, status=WorkerStatus.OFFLINE),
        ]
    )
    db_session.commit()

    headers = auth_headers("owner-1@test.local", "super-secret-password")
    response = client.get("/workers", headers=headers)

    assert response.status_code == 200
    names = [worker["name"] for worker in response.json()["workers"]]
    assert names == ["worker-owned"]


def test_heartbeat_requires_worker_ownership(client: TestClient, create_user, auth_headers, db_session: Session) -> None:
    owner_1 = create_user(email="heart-owner-1@test.local", role=Role.WORKER_OWNER)
    owner_2 = create_user(email="heart-owner-2@test.local", role=Role.WORKER_OWNER)
    worker = Worker(name="worker-heart", owner_user_id=owner_2.id, status=WorkerStatus.OFFLINE)
    db_session.add(worker)
    db_session.commit()

    headers = auth_headers("heart-owner-1@test.local", "super-secret-password")
    response = client.post("/workers/heartbeat", json={"worker_id": worker.id}, headers=headers)

    assert response.status_code == 404


def test_poll_returns_pending_assignment_for_owned_worker(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="poll-owner@test.local", role=Role.WORKER_OWNER)
    worker = Worker(name="worker-poll", owner_user_id=owner.id, status=WorkerStatus.OFFLINE)
    job = Job(
        created_by_user_id=owner.id,
        job_type=JobType.INFERENCE,
        status=JobStatus.QUEUED,
        payload={"prompt": "hello"},
        priority=99,
    )
    db_session.add_all([worker, job])
    db_session.flush()
    db_session.add(
        Assignment(
            job_id=job.id,
            worker_id=worker.id,
            status=AssignmentStatus.PENDING,
            assigned_at=datetime.now(UTC),
            nonce="nonce-poll-1",
        )
    )
    db_session.commit()

    headers = auth_headers("poll-owner@test.local", "super-secret-password")
    response = client.post("/jobs/poll", json={"worker_id": worker.id}, headers=headers)

    assert response.status_code == 200
    assert response.json()["nonce"] == "nonce-poll-1"
    assert response.json()["job"] == {"prompt": "hello"}


def test_submit_validates_nonce_signature_and_replay(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="submit-owner@test.local", role=Role.WORKER_OWNER)
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    worker = Worker(
        name="worker-submit",
        owner_user_id=owner.id,
        status=WorkerStatus.OFFLINE,
        public_key=base64.urlsafe_b64encode(public_key_bytes).decode().rstrip("="),
    )
    job = Job(
        created_by_user_id=owner.id,
        job_type=JobType.INFERENCE,
        status=JobStatus.RUNNING,
        payload={"prompt": "submit"},
    )
    db_session.add_all([worker, job])
    db_session.flush()

    assignment = Assignment(
        job_id=job.id,
        worker_id=worker.id,
        status=AssignmentStatus.PENDING,
        assigned_at=datetime.now(UTC),
        nonce="nonce-submit-1",
    )
    db_session.add(assignment)
    db_session.commit()

    headers = auth_headers("submit-owner@test.local", "super-secret-password")

    invalid_nonce = client.post(
        "/jobs/submit",
        json={
            "worker_id": worker.id,
            "assignment_id": assignment.id,
            "nonce": "wrong",
            "signature": "c2ln",
            "output": {"ok": True},
            "output_hash": "hash-1",
        },
        headers=headers,
    )
    assert invalid_nonce.status_code == 400

    invalid_signature = client.post(
        "/jobs/submit",
        json={
            "worker_id": worker.id,
            "assignment_id": assignment.id,
            "nonce": assignment.nonce,
            "signature": "@@@",
            "output": {"ok": True},
            "output_hash": "hash-1",
        },
        headers=headers,
    )
    assert invalid_signature.status_code == 400

    signed_message = canonical_json(
        {
            "assignment_id": assignment.id,
            "nonce": assignment.nonce,
            "output_hash": "hash-1",
        }
    )
    signature = base64.urlsafe_b64encode(private_key.sign(signed_message)).decode().rstrip("=")

    ok_submit = client.post(
        "/jobs/submit",
        json={
            "worker_id": worker.id,
            "assignment_id": assignment.id,
            "nonce": assignment.nonce,
            "signature": signature,
            "output": {"ok": True},
            "output_hash": "hash-1",
        },
        headers=headers,
    )
    assert ok_submit.status_code == 200

    replay = client.post(
        "/jobs/submit",
        json={
            "worker_id": worker.id,
            "assignment_id": assignment.id,
            "nonce": assignment.nonce,
            "signature": signature,
            "output": {"ok": True},
            "output_hash": "hash-1",
        },
        headers=headers,
    )
    assert replay.status_code == 409

    result = db_session.scalar(select(Result).where(Result.assignment_id == assignment.id))
    assert result is not None
