from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models.enums import AssignmentStatus, VerificationStatus, WorkerStatus
from app.db.models.jobs import Assignment, Result
from app.db.models.pool import PoolSettings
from app.db.models.workers import Worker

VERIFIED_REPUTATION_DELTA = Decimal("0.01")
REJECTED_REPUTATION_DELTA = Decimal("-0.05")


@dataclass(frozen=True)
class AuditPolicy:
    audit_interval_jobs: int
    audit_job_rate_bps: int
    embed_similarity_threshold: float
    fraud_ban_threshold: int


@dataclass(frozen=True)
class VerificationOutcome:
    status: VerificationStatus


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def cosine_similarity(embedding_1: object, embedding_2: object) -> float | None:
    if not isinstance(embedding_1, list) or not isinstance(embedding_2, list):
        return None
    if not embedding_1 or len(embedding_1) != len(embedding_2):
        return None

    vector_1 = [_safe_float(item) for item in embedding_1]
    vector_2 = [_safe_float(item) for item in embedding_2]
    if any(item is None for item in vector_1) or any(item is None for item in vector_2):
        return None

    left = [item for item in vector_1 if item is not None]
    right = [item for item in vector_2 if item is not None]
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    norm_1 = sum(value * value for value in left) ** 0.5
    norm_2 = sum(value * value for value in right) ** 0.5
    if norm_1 == 0 or norm_2 == 0:
        return None

    similarity = dot_product / (norm_1 * norm_2)
    return float(similarity)


def _extract_embedding(output: object) -> object:
    if isinstance(output, dict):
        embedding = output.get("embedding")
        if isinstance(embedding, list):
            return embedding
    return output

def load_audit_policy(db: Session) -> AuditPolicy:
    settings = db.get(PoolSettings, 1)
    if settings is None:
        return AuditPolicy(
            audit_interval_jobs=0,
            audit_job_rate_bps=0,
            embed_similarity_threshold=0.985,
            fraud_ban_threshold=2,
        )

    return AuditPolicy(
        audit_interval_jobs=settings.audit_interval_jobs,
        audit_job_rate_bps=settings.audit_job_rate_bps,
        embed_similarity_threshold=float(settings.embed_similarity_threshold),
        fraud_ban_threshold=settings.fraud_ban_threshold,
    )


def should_mark_new_job_as_audit(db: Session) -> bool:
    policy = load_audit_policy(db)
    if policy.audit_interval_jobs <= 0 or policy.audit_job_rate_bps <= 0:
        return False

    total_jobs = db.scalar(select(func.count()).select_from(Assignment))
    if not isinstance(total_jobs, int) or total_jobs <= 0:
        return False

    if total_jobs % policy.audit_interval_jobs != 0:
        return False

    return policy.audit_job_rate_bps >= 10_000


def _adjust_worker_reputation(worker: Worker, *, delta: Decimal, rejected: bool, fraud_ban_threshold: int) -> None:
    specs = worker.specs_json if isinstance(worker.specs_json, dict) else {}
    specs = dict(specs)

    current_reputation = specs.get("reputation", 0.5)
    reputation_value = Decimal(str(current_reputation if isinstance(current_reputation, (int, float)) else 0.5))
    updated_reputation = min(Decimal("1.0"), max(Decimal("0.0"), reputation_value + delta))
    specs["reputation"] = float(updated_reputation)

    if not rejected:
        worker.specs_json = specs
        return

    rejected_count = specs.get("rejected_submissions", 0)
    rejected_value = int(rejected_count) + 1 if isinstance(rejected_count, int) else 1
    specs["rejected_submissions"] = rejected_value
    worker.specs_json = specs
    if rejected_value >= fraud_ban_threshold:
        worker.status = WorkerStatus.BANNED


def _ensure_third_assignment(db: Session, assignment: Assignment) -> None:
    existing_count = db.scalar(select(func.count()).select_from(Assignment).where(Assignment.job_id == assignment.job_id))
    if isinstance(existing_count, int) and existing_count >= 3:
        return

    db.add(
        Assignment(
            job_id=assignment.job_id,
            worker_id=None,
            status=AssignmentStatus.ASSIGNED,
            assigned_at=datetime.now(UTC),
            nonce=f"audit-third-{uuid4().hex}",
        )
    )


def _process_canonical_job(policy: AuditPolicy, assignment: Assignment, result: Result) -> VerificationOutcome:
    expected_hash = assignment.job.canonical_expected_hash if assignment.job else None
    if expected_hash is None:
        return VerificationOutcome(status=VerificationStatus.PENDING)

    if result.output_hash == expected_hash:
        result.verification_status = VerificationStatus.VERIFIED
        result.verification_score = Decimal("1.0")
        if assignment.worker is not None:
            _adjust_worker_reputation(
                assignment.worker,
                delta=VERIFIED_REPUTATION_DELTA,
                rejected=False,
                fraud_ban_threshold=policy.fraud_ban_threshold,
            )
        return VerificationOutcome(status=VerificationStatus.VERIFIED)

    result.verification_status = VerificationStatus.REJECTED
    result.verification_score = Decimal("0.0")
    assignment.status = AssignmentStatus.FAILED
    if assignment.worker is not None:
        _adjust_worker_reputation(
            assignment.worker,
            delta=REJECTED_REPUTATION_DELTA,
            rejected=True,
            fraud_ban_threshold=policy.fraud_ban_threshold,
        )
    return VerificationOutcome(status=VerificationStatus.REJECTED)


def process_submission_verification(db: Session, assignment: Assignment, result: Result) -> VerificationOutcome:
    policy = load_audit_policy(db)

    if assignment.job and assignment.job.canonical_expected_hash is not None:
        return _process_canonical_job(policy, assignment, result)

    peer_assignment = db.scalar(
        select(Assignment)
        .options(joinedload(Assignment.result), joinedload(Assignment.worker))
        .where(
            Assignment.job_id == assignment.job_id,
            Assignment.id != assignment.id,
            Assignment.result.has(),
        )
        .order_by(Assignment.id.asc())
    )
    if peer_assignment is None or peer_assignment.result is None:
        return VerificationOutcome(status=VerificationStatus.PENDING)

    similarity = cosine_similarity(_extract_embedding(peer_assignment.result.output), _extract_embedding(result.output))
    if similarity is not None and similarity >= policy.embed_similarity_threshold:
        result.verification_status = VerificationStatus.VERIFIED
        result.verification_score = Decimal(str(similarity))
        peer_assignment.result.verification_status = VerificationStatus.VERIFIED
        peer_assignment.result.verification_score = Decimal(str(similarity))

        if assignment.worker is not None:
            _adjust_worker_reputation(
                assignment.worker,
                delta=VERIFIED_REPUTATION_DELTA,
                rejected=False,
                fraud_ban_threshold=policy.fraud_ban_threshold,
            )
        if peer_assignment.worker is not None:
            _adjust_worker_reputation(
                peer_assignment.worker,
                delta=VERIFIED_REPUTATION_DELTA,
                rejected=False,
                fraud_ban_threshold=policy.fraud_ban_threshold,
            )
        return VerificationOutcome(status=VerificationStatus.VERIFIED)

    result.verification_status = VerificationStatus.DISPUTED
    peer_assignment.result.verification_status = VerificationStatus.DISPUTED
    _ensure_third_assignment(db, assignment)
    return VerificationOutcome(status=VerificationStatus.DISPUTED)
