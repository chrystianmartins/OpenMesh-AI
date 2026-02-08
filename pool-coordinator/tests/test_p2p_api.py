from __future__ import annotations

from app.db.models.accounting import LedgerEntry
from app.db.models.enums import JobStatus, JobType, WorkerStatus
from app.db.models.jobs import Job
from app.db.models.p2p import Peer
from app.db.models.workers import Worker, WorkerSettings


def _allowlisted_peer(db_session) -> Peer:
    peer = Peer(peer_id="peer-a", url="https://peer-a.local", shared_secret="shared-secret-123")
    db_session.add(peer)
    db_session.commit()
    db_session.refresh(peer)
    return peer


def test_register_peer_updates_last_seen(client, db_session):
    _allowlisted_peer(db_session)

    response = client.post(
        "/p2p/peers/register",
        json={
            "peer_id": "peer-a",
            "url": "https://peer-a-updated.local",
            "shared_secret": "shared-secret-123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["peer_id"] == "peer-a"
    assert payload["url"] == "https://peer-a-updated.local"
    assert payload["last_seen"]


def test_forward_job_rejected_without_capacity(client, db_session):
    _allowlisted_peer(db_session)

    response = client.post(
        "/p2p/jobs/forward",
        json={
            "peer_id": "peer-a",
            "shared_secret": "shared-secret-123",
            "origin_job_id": "origin-1",
            "origin_pool": "pool-origin",
            "job_type": JobType.INFERENCE.value,
            "payload": {"prompt": "hi"},
            "priority": 10,
        },
    )

    assert response.status_code == 503


def test_forward_job_creates_local_job_and_interpool_ledger(client, db_session):
    _allowlisted_peer(db_session)

    worker = Worker(name="worker-p2p", owner_user_id=999, status=WorkerStatus.ONLINE)
    db_session.add(worker)
    db_session.flush()
    db_session.add(WorkerSettings(worker_id=worker.id, max_concurrency=2, accept_new_assignments=True))
    db_session.commit()

    response = client.post(
        "/p2p/jobs/forward",
        json={
            "peer_id": "peer-a",
            "shared_secret": "shared-secret-123",
            "origin_job_id": "origin-2",
            "origin_pool": "pool-origin",
            "job_type": JobType.INFERENCE.value,
            "payload": {"prompt": "federated"},
            "priority": 5,
        },
    )

    assert response.status_code == 200
    local_job_id = response.json()["local_job_id"]
    job = db_session.get(Job, local_job_id)
    assert job is not None
    assert job.payload["federation"]["origin_job_id"] == "origin-2"

    ledger = db_session.query(LedgerEntry).filter(LedgerEntry.job_id == local_job_id).all()
    assert any(entry.entry_type == "interpool_fee" for entry in ledger)


def test_relay_result_updates_job_and_logs_ledger(client, db_session):
    _allowlisted_peer(db_session)

    job = Job(created_by_user_id=None, job_type=JobType.INFERENCE, status=JobStatus.RUNNING, payload={"x": 1}, priority=0)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    response = client.post(
        "/p2p/results/relay",
        json={
            "peer_id": "peer-a",
            "shared_secret": "shared-secret-123",
            "local_job_id": job.id,
            "output": {"ok": True},
            "output_hash": "hash-1",
        },
    )

    assert response.status_code == 200
    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.payload["relayed_result"]["output_hash"] == "hash-1"

    ledger_entries = db_session.query(LedgerEntry).filter(LedgerEntry.job_id == job.id).all()
    assert any(entry.entry_type == "interpool_fee" for entry in ledger_entries)


def test_allowlist_enforced(client, db_session):
    response = client.post(
        "/p2p/peers/register",
        json={
            "peer_id": "unknown-peer",
            "url": "https://unknown.local",
            "shared_secret": "shared-secret-123",
        },
    )

    assert response.status_code == 403
