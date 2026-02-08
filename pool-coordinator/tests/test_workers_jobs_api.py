from __future__ import annotations

import base64
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.protocol_crypto import canonical_json
from app.db.models.enums import AssignmentStatus, JobStatus, JobType, Role, VerificationStatus, WorkerStatus
from app.db.models.jobs import Assignment, Job, Result
from app.db.models.pool import PoolSettings
from app.db.models.workers import Worker


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
    create_user(email="heart-owner-1@test.local", role=Role.WORKER_OWNER)
    owner_2 = create_user(email="heart-owner-2@test.local", role=Role.WORKER_OWNER)
    worker = Worker(name="worker-heart", owner_user_id=owner_2.id, status=WorkerStatus.OFFLINE)
    db_session.add(worker)
    db_session.commit()

    headers = auth_headers("heart-owner-1@test.local", "super-secret-password")
    response = client.post("/workers/heartbeat", json={"worker_id": worker.id}, headers=headers)

    assert response.status_code == 404


def test_poll_returns_assigned_assignment_for_owned_worker(
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
            status=AssignmentStatus.ASSIGNED,
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


def _sign_submission(private_key: Ed25519PrivateKey, assignment_id: int, nonce: str, output_hash: str) -> str:
    signed_message = canonical_json(
        {
            "assignment_id": assignment_id,
            "nonce": nonce,
            "output_hash": output_hash,
        }
    )
    return base64.urlsafe_b64encode(private_key.sign(signed_message)).decode().rstrip("=")


def _make_worker(owner_id: int, name: str) -> tuple[Worker, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    worker = Worker(
        name=name,
        owner_user_id=owner_id,
        status=WorkerStatus.OFFLINE,
        public_key=base64.urlsafe_b64encode(public_key_bytes).decode().rstrip("="),
        specs_json={"reputation": 0.5},
    )
    return worker, private_key


def test_submit_validates_nonce_signature_and_replay(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="submit-owner@test.local", role=Role.WORKER_OWNER)
    worker, private_key = _make_worker(owner.id, "worker-submit")

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
        status=AssignmentStatus.ASSIGNED,
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

    signature = _sign_submission(private_key, assignment.id, assignment.nonce, "hash-1")

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


def test_second_matching_embedding_marks_verified_and_increases_reputation(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="verify-owner@test.local", role=Role.WORKER_OWNER)
    worker_1, key_1 = _make_worker(owner.id, "worker-verify-1")
    worker_2, key_2 = _make_worker(owner.id, "worker-verify-2")

    db_session.add(PoolSettings(id=1, embed_similarity_threshold=0.985))
    job = Job(created_by_user_id=owner.id, job_type=JobType.EMBEDDING, status=JobStatus.RUNNING, payload={"kind": "embed"})
    db_session.add_all([worker_1, worker_2, job])
    db_session.flush()

    assignment_1 = Assignment(job_id=job.id, worker_id=worker_1.id, status=AssignmentStatus.ASSIGNED, assigned_at=datetime.now(UTC), nonce="nonce-v-1")
    assignment_2 = Assignment(job_id=job.id, worker_id=worker_2.id, status=AssignmentStatus.ASSIGNED, assigned_at=datetime.now(UTC), nonce="nonce-v-2")
    db_session.add_all([assignment_1, assignment_2])
    db_session.commit()

    headers = auth_headers("verify-owner@test.local", "super-secret-password")
    signature_1 = _sign_submission(key_1, assignment_1.id, assignment_1.nonce, "h1")
    signature_2 = _sign_submission(key_2, assignment_2.id, assignment_2.nonce, "h2")

    submit_1 = client.post(
        "/jobs/submit",
        json={"worker_id": worker_1.id, "assignment_id": assignment_1.id, "nonce": assignment_1.nonce, "signature": signature_1, "output": {"embedding": [1.0, 0.0]}, "output_hash": "h1"},
        headers=headers,
    )
    assert submit_1.status_code == 200

    submit_2 = client.post(
        "/jobs/submit",
        json={"worker_id": worker_2.id, "assignment_id": assignment_2.id, "nonce": assignment_2.nonce, "signature": signature_2, "output": {"embedding": [0.999, 0.001]}, "output_hash": "h2"},
        headers=headers,
    )
    assert submit_2.status_code == 200

    result_1 = db_session.scalar(select(Result).where(Result.assignment_id == assignment_1.id))
    result_2 = db_session.scalar(select(Result).where(Result.assignment_id == assignment_2.id))
    assert result_1 is not None and result_2 is not None
    assert result_1.verification_status == VerificationStatus.VERIFIED
    assert result_2.verification_status == VerificationStatus.VERIFIED


def test_disputed_embedding_creates_third_assignment(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="dispute-owner@test.local", role=Role.WORKER_OWNER)
    worker_1, key_1 = _make_worker(owner.id, "worker-dispute-1")
    worker_2, key_2 = _make_worker(owner.id, "worker-dispute-2")

    db_session.add(PoolSettings(id=1, embed_similarity_threshold=0.985))
    job = Job(created_by_user_id=owner.id, job_type=JobType.EMBEDDING, status=JobStatus.RUNNING, payload={"kind": "embed"})
    db_session.add_all([worker_1, worker_2, job])
    db_session.flush()

    assignment_1 = Assignment(job_id=job.id, worker_id=worker_1.id, status=AssignmentStatus.ASSIGNED, assigned_at=datetime.now(UTC), nonce="nonce-d-1")
    assignment_2 = Assignment(job_id=job.id, worker_id=worker_2.id, status=AssignmentStatus.ASSIGNED, assigned_at=datetime.now(UTC), nonce="nonce-d-2")
    db_session.add_all([assignment_1, assignment_2])
    db_session.commit()

    headers = auth_headers("dispute-owner@test.local", "super-secret-password")
    signature_1 = _sign_submission(key_1, assignment_1.id, assignment_1.nonce, "h1")
    signature_2 = _sign_submission(key_2, assignment_2.id, assignment_2.nonce, "h2")

    assert client.post(
        "/jobs/submit",
        json={"worker_id": worker_1.id, "assignment_id": assignment_1.id, "nonce": assignment_1.nonce, "signature": signature_1, "output": {"embedding": [1.0, 0.0]}, "output_hash": "h1"},
        headers=headers,
    ).status_code == 200

    assert client.post(
        "/jobs/submit",
        json={"worker_id": worker_2.id, "assignment_id": assignment_2.id, "nonce": assignment_2.nonce, "signature": signature_2, "output": {"embedding": [0.0, 1.0]}, "output_hash": "h2"},
        headers=headers,
    ).status_code == 200

    assignments = db_session.scalars(select(Assignment).where(Assignment.job_id == job.id).order_by(Assignment.id.asc())).all()
    assert len(assignments) == 3
    assert assignments[2].worker_id is None


def test_canonical_job_rejects_cheater_and_bans_on_repeat(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    owner = create_user(email="canonical-owner@test.local", role=Role.WORKER_OWNER)
    worker, key = _make_worker(owner.id, "worker-canonical")
    db_session.add(PoolSettings(id=1, fraud_ban_threshold=2))

    job_1 = Job(
        created_by_user_id=owner.id,
        job_type=JobType.INFERENCE,
        status=JobStatus.RUNNING,
        payload={"trap": 1},
        canonical_expected_hash="expected-hash",
    )
    job_2 = Job(
        created_by_user_id=owner.id,
        job_type=JobType.INFERENCE,
        status=JobStatus.RUNNING,
        payload={"trap": 2},
        canonical_expected_hash="expected-hash-2",
    )
    db_session.add_all([worker, job_1, job_2])
    db_session.flush()

    assignment_1 = Assignment(job_id=job_1.id, worker_id=worker.id, status=AssignmentStatus.ASSIGNED, assigned_at=datetime.now(UTC), nonce="nonce-c-1")
    assignment_2 = Assignment(job_id=job_2.id, worker_id=worker.id, status=AssignmentStatus.ASSIGNED, assigned_at=datetime.now(UTC), nonce="nonce-c-2")
    db_session.add_all([assignment_1, assignment_2])
    db_session.commit()

    headers = auth_headers("canonical-owner@test.local", "super-secret-password")

    bad_sig_1 = _sign_submission(key, assignment_1.id, assignment_1.nonce, "bad-1")
    bad_sig_2 = _sign_submission(key, assignment_2.id, assignment_2.nonce, "bad-2")

    assert client.post(
        "/jobs/submit",
        json={"worker_id": worker.id, "assignment_id": assignment_1.id, "nonce": assignment_1.nonce, "signature": bad_sig_1, "output": {"x": 1}, "output_hash": "bad-1"},
        headers=headers,
    ).status_code == 200

    assert client.post(
        "/jobs/submit",
        json={"worker_id": worker.id, "assignment_id": assignment_2.id, "nonce": assignment_2.nonce, "signature": bad_sig_2, "output": {"x": 2}, "output_hash": "bad-2"},
        headers=headers,
    ).status_code == 200

    result_1 = db_session.scalar(select(Result).where(Result.assignment_id == assignment_1.id))
    result_2 = db_session.scalar(select(Result).where(Result.assignment_id == assignment_2.id))
    db_session.refresh(worker)

    assert result_1 is not None and result_2 is not None
    assert result_1.verification_status == VerificationStatus.REJECTED
    assert result_2.verification_status == VerificationStatus.REJECTED
    assert worker.status == WorkerStatus.BANNED
