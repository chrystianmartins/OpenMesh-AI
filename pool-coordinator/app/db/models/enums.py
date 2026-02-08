from enum import Enum


class Role(str, Enum):
    CLIENT = "client"
    WORKER_OWNER = "worker_owner"


class WorkerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    MAINTENANCE = "maintenance"
    BANNED = "banned"


class JobType(str, Enum):
    INFERENCE = "inference"
    FINE_TUNING = "fine_tuning"
    EMBEDDING = "embedding"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class AssignmentStatus(str, Enum):
    ASSIGNED = "assigned"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class OwnerType(str, Enum):
    USER = "user"
    WORKER = "worker"
    SYSTEM = "system"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    REJECTED = "rejected"
