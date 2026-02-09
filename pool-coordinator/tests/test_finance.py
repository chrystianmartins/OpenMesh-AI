from __future__ import annotations

import base64
from datetime import UTC, datetime
from decimal import Decimal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.protocol_crypto import canonical_json
from app.db.models.accounting import Account, LedgerEntry
from app.db.models.enums import AssignmentStatus, JobStatus, JobType, OwnerType, Role, WorkerStatus
from app.db.models.jobs import Assignment, Job
from app.db.models.pool import PoolSettings, PricingRule
from app.db.models.workers import Worker


def _sign_submission(private_key: Ed25519PrivateKey, assignment_id: int, nonce: str, output_hash: str) -> str:
    signed_message = canonical_json(
        {
            "assignment_id": assignment_id,
            "nonce": nonce,
            "output_hash": output_hash,
        }
    )
    return base64.urlsafe_b64encode(private_key.sign(signed_message)).decode().rstrip("=")


def test_verified_job_posts_ledger_entries_and_balances(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    client_user = create_user(email="finance-client@test.local", role=Role.CLIENT)
    owner = create_user(email="finance-owner@test.local", role=Role.WORKER_OWNER)

    private_key = Ed25519PrivateKey.generate()
    public_key = base64.urlsafe_b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode().rstrip("=")

    worker = Worker(name="worker-finance", owner_user_id=owner.id, status=WorkerStatus.OFFLINE, public_key=public_key)
    db_session.add_all(
        [
            PoolSettings(id=1, pool_fee_bps=1000),
            PricingRule(
                name="FINANCE-RULE",
                job_type=JobType.INFERENCE,
                unit_price=Decimal("0.0001"),
                unit_cost_tokens=Decimal("50"),
                minimum_charge=Decimal("0"),
                is_active=True,
                effective_from=datetime.now(UTC),
            ),
            worker,
        ]
    )
    db_session.flush()

    job = Job(
        created_by_user_id=client_user.id,
        job_type=JobType.INFERENCE,
        status=JobStatus.RUNNING,
        payload={"prompt": "a" * 1500},
    )
    db_session.add(job)
    db_session.flush()

    assignment_1 = Assignment(
        job_id=job.id,
        worker_id=worker.id,
        status=AssignmentStatus.ASSIGNED,
        assigned_at=datetime.now(UTC),
        nonce="finance-nonce-1",
    )
    assignment_2 = Assignment(
        job_id=job.id,
        worker_id=worker.id,
        status=AssignmentStatus.ASSIGNED,
        assigned_at=datetime.now(UTC),
        nonce="finance-nonce-2",
    )
    db_session.add_all([assignment_1, assignment_2])
    db_session.commit()

    headers = auth_headers("finance-owner@test.local", "super-secret-password")

    signature_1 = _sign_submission(private_key, assignment_1.id, assignment_1.nonce, "h1")
    signature_2 = _sign_submission(private_key, assignment_2.id, assignment_2.nonce, "h2")

    assert (
        client.post(
            "/jobs/submit",
            json={
                "worker_id": worker.id,
                "assignment_id": assignment_1.id,
                "nonce": assignment_1.nonce,
                "signature": signature_1,
                "output_hash": "h1",
                "output": {"embedding": [1.0, 0.0]},
            },
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/jobs/submit",
            json={
                "worker_id": worker.id,
                "assignment_id": assignment_2.id,
                "nonce": assignment_2.nonce,
                "signature": signature_2,
                "output_hash": "h2",
                "output": {"embedding": [0.9999, 0.0001]},
            },
            headers=headers,
        ).status_code
        == 200
    )

    entries = db_session.scalars(select(LedgerEntry).order_by(LedgerEntry.id.asc())).all()
    assert len(entries) == 3
    assert entries[0].entry_type == "job_charge"
    assert entries[0].amount == Decimal("-100.00000000")
    assert entries[1].entry_type == "pool_fee"
    assert entries[1].amount == Decimal("10.00000000")
    assert entries[2].entry_type == "worker_reward"
    assert entries[2].amount == Decimal("90.00000000")

    client_account = db_session.scalar(
        select(Account).where(
            Account.owner_type == OwnerType.USER,
            Account.owner_id == client_user.id,
            Account.currency == "TOK",
        )
    )
    assert client_account is not None
    assert client_account.balance == Decimal("-100.00000000")


def test_finance_endpoints_balance_ledger_and_summary(
    client: TestClient,
    create_user,
    auth_headers,
    db_session: Session,
) -> None:
    user = create_user(email="finance-me@test.local", role=Role.CLIENT)
    create_user(email="finance-admin@test.local", role=Role.WORKER_OWNER)

    account = Account(owner_type=OwnerType.USER, owner_id=user.id, currency="TOK", balance=Decimal("5.5"))
    db_session.add(account)
    db_session.flush()
    db_session.add(
        LedgerEntry(
            account_id=account.id,
            amount=Decimal("5.5"),
            entry_type="credit",
            details={"source": "seed"},
        )
    )
    db_session.commit()

    headers = auth_headers("finance-me@test.local", "super-secret-password")
    balance_response = client.get("/me/balance", headers=headers)
    assert balance_response.status_code == 200
    assert balance_response.json()["balance"] == "5.50000000"

    ledger_response = client.get("/me/ledger?page=1&page_size=10", headers=headers)
    assert ledger_response.status_code == 200
    payload = ledger_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["entry_type"] == "credit"

    admin_headers = auth_headers("finance-admin@test.local", "super-secret-password")
    summary_response = client.get("/admin/finance/summary", headers=admin_headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_accounts"] >= 1
    assert summary["total_ledger_entries"] >= 1
