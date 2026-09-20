from __future__ import annotations

import threading
from datetime import timedelta

from docprod.product.enums import (
    AttemptStatus,
    JobStatus,
    OutboxStatus,
    PlanItemType,
    ProviderBilledStatus,
    ProviderOutcome,
)
from docprod.product.errors import IdempotencyConflictError
from docprod.product.models import GenerationJob, IdempotencyRecord, TelegramUser, utcnow
from docprod.product.notifications import MockNotificationSender, drain_outbox
from docprod.product.repository import MemoryRepository
from docprod.product.services import ProductService
from docprod.product.worker import MockGenerationWorker


def _authorized_job() -> tuple[ProductService, GenerationJob]:
    svc = ProductService()
    user = svc.repo.put_user(TelegramUser(telegram_user_id=7, first_name="T"))
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    payment = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="p-auth", stars=quote.stars
    )
    job = svc.authorize_generation(user.id, quote.id, payment.id)
    return svc, job


def test_two_workers_claim_one_job() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    hits: list[str] = []

    def claim(name: str) -> None:
        got = service.repo.claim_queued_job(name, lease=timedelta(seconds=30))
        if got is not None:
            hits.append(got.id)

    t1 = threading.Thread(target=claim, args=("w1",))
    t2 = threading.Thread(target=claim, args=("w2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert hits == [job.id]
    assert service.repo.jobs[job.id].claimed_by in {"w1", "w2"}


def test_expired_lease_recovered_by_second_worker() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    first = service.repo.claim_queued_job("w-a", now=utcnow() - timedelta(minutes=5))
    assert first is not None
    job.lease_expires_at = utcnow() - timedelta(seconds=1)
    second = service.repo.claim_queued_job("w-b")
    assert second is not None
    assert second.claimed_by == "w-b"
    MockGenerationWorker(service, worker_id="w-b").run_job(job.id)
    assert service.repo.jobs[job.id].status is JobStatus.COMPLETED


def test_crash_recovery_does_not_resubmit_remote_operation() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    service.advance_job(job.id, JobStatus.PLANNING)
    service.advance_job(job.id, JobStatus.GENERATING_SCRIPT)
    service.advance_job(job.id, JobStatus.GENERATING_IMAGES)
    service.advance_job(job.id, JobStatus.GENERATING_VIDEO)
    attempt = service.record_attempt(
        job.id,
        item_type=PlanItemType.VIDEO,
        provider="mock",
        model="veo-mock",
        outcome=ProviderOutcome.SUCCEEDED,
        billed=ProviderBilledStatus.UNKNOWN,
        status=AttemptStatus.SUBMITTED,
        remote_operation_id="op-remote-1",
        estimated_provider_cost=0.4,
    )
    recovered = service.recover_uncertain_paid_attempts(job.id)
    assert [row.id for row in recovered] == [attempt.id]
    MockGenerationWorker(service, worker_id="w-recover").run_job(job.id)
    remotes = [a for a in service.repo.attempts_for_job(job.id) if a.remote_operation_id]
    assert len(remotes) == 1
    assert remotes[0].remote_operation_id == "op-remote-1"
    assert service.repo.jobs[job.id].status is JobStatus.COMPLETED


def test_outbox_completes_with_job_and_sender_is_idempotent() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    MockGenerationWorker(service).run_job(job.id)
    notes = [n for n in service.repo.outbox.values() if n.job_id == job.id]
    assert len(notes) == 1
    assert notes[0].status is OutboxStatus.PENDING
    sender = MockNotificationSender()
    assert drain_outbox(service.repo, sender) == 1
    assert drain_outbox(service.repo, sender) == 0
    assert sender.sent == [notes[0].id]
    assert service.repo.outbox[notes[0].id].status is OutboxStatus.SENT


def test_idempotency_conflict_on_memory_repo() -> None:
    repo = MemoryRepository()
    first = repo.put_idempotency(
        IdempotencyRecord(
            key="k1",
            user_id="u1",
            action="generate",
            request_hash="aaa",
            status_code=202,
            body={"job_id": "j1"},
        )
    )
    again = repo.put_idempotency(
        IdempotencyRecord(
            key="k1",
            user_id="u1",
            action="generate",
            request_hash="aaa",
            status_code=202,
            body={"job_id": "j1"},
        )
    )
    assert again.id == first.id
    try:
        repo.put_idempotency(
            IdempotencyRecord(
                key="k1",
                user_id="u1",
                action="generate",
                request_hash="bbb",
                status_code=202,
                body={"job_id": "j2"},
            )
        )
        raise AssertionError("expected conflict")
    except IdempotencyConflictError:
        pass


def test_duplicate_payment_does_not_double_ledger() -> None:
    svc = ProductService()
    user = svc.repo.put_user(TelegramUser(telegram_user_id=9, first_name="T"))
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    first = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="sim-dup", stars=quote.stars
    )
    second = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="sim-dup", stars=quote.stars
    )
    assert first.id == second.id
    pays = [p for p in svc.repo.payments.values() if p.telegram_payment_id == "sim-dup"]
    assert len(pays) == 1
    txns = [t for t in svc.repo.transactions.values() if t.telegram_payment_id == "sim-dup"]
    assert len(txns) == 1


def test_provider_cap_blocks_worker() -> None:
    service, job = _authorized_job()
    job.reserved_provider_cost = 99
    job.provider_cost_cap = 1
    service.start_generation(job.user_id, job.id)
    MockGenerationWorker(service).run_job(job.id)
    stored = service.repo.jobs[job.id]
    assert stored.status is JobStatus.FAILED
    assert stored.error_code == "PROVIDER_CAP_EXCEEDED"
    assert stored.failure_message
    assert "traceback" not in stored.failure_message.lower()


def test_archive_is_soft_delete() -> None:
    service, job = _authorized_job()
    project = service.archive_project(job.user_id, job.project_id)
    assert project.archived_at is not None
    assert job.project_id in service.repo.projects


def test_request_id_header_round_trip() -> None:
    from fastapi.testclient import TestClient

    from docprod.api.app import create_app

    client = TestClient(create_app(env="test"))
    response = client.get("/health", headers={"X-Request-ID": "req-abc-1"})
    assert response.headers["X-Request-ID"] == "req-abc-1"
    assert response.json()["status"] == "ok"
