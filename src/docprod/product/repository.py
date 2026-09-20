from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TypeVar

from docprod.product.enums import JobStatus, OutboxStatus
from docprod.product.errors import IdempotencyConflictError, JobConflictError
from docprod.product.models import (
    Asset,
    AssetVersion,
    Character,
    CharacterReference,
    GenerationAttempt,
    GenerationJob,
    GenerationPlan,
    IdempotencyRecord,
    NotificationOutbox,
    Project,
    Render,
    Scene,
    SceneVersion,
    ScriptVersion,
    StarQuote,
    StarTransaction,
    TelegramPayment,
    TelegramUser,
    WorkerHeartbeat,
    utcnow,
)

T = TypeVar("T")

TERMINAL_JOB = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
)

CLAIMABLE_JOB = frozenset(
    {
        JobStatus.QUEUED,
        JobStatus.PLANNING,
        JobStatus.GENERATING_SCRIPT,
        JobStatus.GENERATING_IMAGES,
        JobStatus.GENERATING_VIDEO,
        JobStatus.GENERATING_AUDIO,
        JobStatus.RENDERING,
        JobStatus.RECOVERING_REMOTE,
        JobStatus.PARTIAL,
    }
)


class MemoryRepository:
    """In-memory / JSON-backed product store. PostgresRepository subclasses this."""

    def __init__(self) -> None:
        self.users: dict[str, TelegramUser] = {}
        self.users_by_telegram: dict[int, str] = {}
        self.projects: dict[str, Project] = {}
        self.characters: dict[str, Character] = {}
        self.references: dict[str, CharacterReference] = {}
        self.scripts: dict[str, ScriptVersion] = {}
        self.scenes: dict[str, Scene] = {}
        self.scene_versions: dict[str, SceneVersion] = {}
        self.assets: dict[str, Asset] = {}
        self.asset_versions: dict[str, AssetVersion] = {}
        self.plans: dict[str, GenerationPlan] = {}
        self.quotes: dict[str, StarQuote] = {}
        self.jobs: dict[str, GenerationJob] = {}
        self.attempts: dict[str, GenerationAttempt] = {}
        self.renders: dict[str, Render] = {}
        self.transactions: dict[str, StarTransaction] = {}
        self.txn_by_idempotency: dict[str, str] = {}
        self.payments: dict[str, TelegramPayment] = {}
        self.payments_by_telegram: dict[str, str] = {}
        self.outbox: dict[str, NotificationOutbox] = {}
        self.idempotency: dict[str, IdempotencyRecord] = {}
        self.workers: dict[str, WorkerHeartbeat] = {}
        self._lock = threading.Lock()

    @contextmanager
    def transaction(self):
        yield self

    def persistence_kind(self) -> str:
        return "json"

    def ping(self) -> bool:
        return True

    def put_user(self, user: TelegramUser) -> TelegramUser:
        existing = self.users_by_telegram.get(user.telegram_user_id)
        if existing:
            stored = self.users[existing]
            stored.username = user.username
            stored.first_name = user.first_name
            stored.language_code = user.language_code
            stored.updated_at = user.updated_at
            return stored
        self.users[user.id] = user
        self.users_by_telegram[user.telegram_user_id] = user.id
        return user

    def user_by_id(self, user_id: str) -> TelegramUser:
        return self.users[user_id]

    def user_by_telegram(self, telegram_user_id: int) -> TelegramUser | None:
        uid = self.users_by_telegram.get(telegram_user_id)
        return self.users.get(uid) if uid else None

    def put_project(self, project: Project) -> Project:
        self.projects[project.id] = project
        return project

    def projects_for(self, user_id: str) -> list[Project]:
        return [p for p in self.projects.values() if p.user_id == user_id]

    def characters_for(self, project_id: str) -> list[Character]:
        return [c for c in self.characters.values() if c.project_id == project_id]

    def scenes_for(self, project_id: str) -> list[Scene]:
        rows = [s for s in self.scenes.values() if s.project_id == project_id]
        return sorted(rows, key=lambda s: s.order_index)

    def active_versions(self, project_id: str) -> list[SceneVersion]:
        versions: list[SceneVersion] = []
        for scene in self.scenes_for(project_id):
            if scene.active_version_id:
                versions.append(self.scene_versions[scene.active_version_id])
        return versions

    def jobs_for_user(self, user_id: str) -> list[GenerationJob]:
        return [j for j in self.jobs.values() if j.user_id == user_id]

    def jobs_for_project(self, project_id: str) -> list[GenerationJob]:
        return [j for j in self.jobs.values() if j.project_id == project_id]

    def active_jobs_for_user(self, user_id: str) -> list[GenerationJob]:
        ignored = TERMINAL_JOB | {JobStatus.PARTIAL}
        return [j for j in self.jobs_for_user(user_id) if j.status not in ignored]

    def active_jobs_for_project(self, project_id: str) -> list[GenerationJob]:
        ignored = TERMINAL_JOB | {JobStatus.PARTIAL}
        return [j for j in self.jobs_for_project(project_id) if j.status not in ignored]

    def put_job(self, job: GenerationJob) -> GenerationJob:
        self.jobs[job.id] = job
        return job

    def put_attempt(self, attempt: GenerationAttempt) -> GenerationAttempt:
        self.attempts[attempt.id] = attempt
        return attempt

    def attempts_for_job(self, job_id: str) -> list[GenerationAttempt]:
        return [a for a in self.attempts.values() if a.job_id == job_id]

    def put_transaction(self, txn: StarTransaction) -> StarTransaction:
        with self._lock:
            existing_id = self.txn_by_idempotency.get(txn.idempotency_key)
            if existing_id:
                existing = self.transactions[existing_id]
                if (
                    existing.user_id != txn.user_id
                    or existing.stars != txn.stars
                    or existing.type != txn.type
                ):
                    raise IdempotencyConflictError("idempotency key reused with different payload")
                return existing
            self.transactions[txn.id] = txn
            self.txn_by_idempotency[txn.idempotency_key] = txn.id
            return txn

    def put_payment(self, payment: TelegramPayment) -> TelegramPayment:
        with self._lock:
            existing_id = self.payments_by_telegram.get(payment.telegram_payment_id)
            if existing_id:
                return self.payments[existing_id]
            self.payments[payment.id] = payment
            self.payments_by_telegram[payment.telegram_payment_id] = payment.id
            return payment

    def idempotency_lookup(self, user_id: str, action: str, key: str) -> IdempotencyRecord | None:
        return self.idempotency.get(f"{user_id}:{action}:{key}")

    def put_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        with self._lock:
            slot = f"{record.user_id}:{record.action}:{record.key}"
            existing = self.idempotency.get(slot)
            if existing:
                if existing.request_hash != record.request_hash:
                    raise IdempotencyConflictError("idempotency key reused with different payload")
                return existing
            self.idempotency[slot] = record
            return record

    def pending_outbox(self, now: datetime | None = None) -> list[NotificationOutbox]:
        stamp = now or utcnow()
        rows = []
        for note in self.outbox.values():
            if note.status is not OutboxStatus.PENDING:
                continue
            if note.next_attempt_at is not None and note.next_attempt_at > stamp:
                continue
            rows.append(note)
        return sorted(rows, key=lambda n: n.created_at)

    def put_outbox(self, note: NotificationOutbox) -> NotificationOutbox:
        self.outbox[note.id] = note
        return note

    def put_worker_heartbeat(self, beat: WorkerHeartbeat) -> WorkerHeartbeat:
        self.workers[beat.worker_id] = beat
        return beat

    def latest_worker_heartbeat(self) -> WorkerHeartbeat | None:
        if not self.workers:
            return None
        return max(self.workers.values(), key=lambda b: b.last_seen_at)

    def claim_queued_job(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease: timedelta = timedelta(seconds=30),
    ) -> GenerationJob | None:
        stamp = now or utcnow()
        with self._lock:
            candidates = []
            for job in self.jobs.values():
                if job.status not in CLAIMABLE_JOB:
                    continue
                expired = job.lease_expires_at is None or job.lease_expires_at <= stamp
                free = job.claimed_by is None or expired
                if free:
                    candidates.append(job)
            if not candidates:
                return None
            job = sorted(candidates, key=lambda j: j.created_at)[0]
            job.claimed_by = worker_id
            job.claimed_at = stamp
            job.heartbeat_at = stamp
            job.lease_expires_at = stamp + lease
            job.attempt_count += 1
            job.updated_at = stamp
            return job

    def heartbeat_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease: timedelta = timedelta(seconds=30),
    ) -> GenerationJob:
        stamp = now or utcnow()
        job = self.jobs[job_id]
        if job.claimed_by != worker_id:
            raise JobConflictError("job lease owned by another worker")
        job.heartbeat_at = stamp
        job.lease_expires_at = stamp + lease
        job.updated_at = stamp
        return job
