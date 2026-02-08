from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Assignment, Job, Result, User, Worker, WorkerSettings
from app.db.models.enums import JobType


def test_basic_relations_and_minimum_domain_defaults(db_session: Session) -> None:
    user = User(email="relations-user@test.local", password_hash="hash")
    worker = Worker(name="worker-a")
    worker_settings = WorkerSettings(worker=worker)
    db_session.add_all([user, worker, worker_settings])
    db_session.flush()

    job = Job(
        created_by_user_id=user.id,
        job_type=JobType.INFERENCE,
        payload={"input": "hello"},
    )
    db_session.add(job)
    db_session.flush()

    assignment = Assignment(
        job=job,
        worker_id=worker.id,
        assigned_at=datetime.now(UTC),
    )
    result = Result(
        assignment=assignment,
        output={"result": "ok"},
    )

    db_session.add_all([assignment, result])
    db_session.commit()
    db_session.refresh(worker)
    db_session.refresh(worker_settings)
    db_session.refresh(job)
    db_session.refresh(assignment)
    db_session.refresh(result)

    assert worker.status.value == "offline"
    assert worker_settings.worker_id == worker.id
    assert worker_settings.max_concurrency == 1
    assert worker_settings.heartbeat_timeout_seconds == 30
    assert worker_settings.pull_interval_seconds == 5
    assert worker_settings.accept_new_assignments is True

    assert job.created_by_user_id == user.id
    assert job.status.value == "queued"
    assert assignment.status.value == "pending"
    assert assignment.job_id == job.id
    assert assignment.worker_id == worker.id
    assert result.assignment_id == assignment.id
