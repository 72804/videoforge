from __future__ import annotations

import inspect
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from tests.product.test_durable_queue import _authorized_job

from docprod.api.app import create_app
from docprod.product.durable import DurableGenerationWorker
from docprod.product.enums import JobStatus, OutboxStatus
from docprod.product.errors import ProductError
from docprod.product.notifications import MockNotificationSender
from docprod.product.storage import PlaceholderStorageBackend
from docprod.product.worker import MockGenerationWorker


def test_run_bounded_has_no_perpetual_loop() -> None:
    source = inspect.getsource(DurableGenerationWorker.run_bounded)
    assert "while " not in source
    assert "for _ in range(limit)" in source
    source_id = inspect.getsource(DurableGenerationWorker.run_job_id)
    assert "while " not in source_id


def test_bounded_executor_completes_and_notifies() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    sender = MockNotificationSender()
    ran = DurableGenerationWorker(
        service, worker_id="serverless", sender=sender
    ).run_bounded(max_jobs=1)
    assert ran == 1
    stored = service.repo.jobs[job.id]
    assert stored.status is JobStatus.COMPLETED
    notes = [n for n in service.repo.outbox.values() if n.job_id == job.id]
    assert notes
    assert sender.sent
    assert all(service.repo.outbox[i].status is OutboxStatus.SENT for i in sender.sent)


def test_duplicate_executor_invocation_is_idempotent() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    sender = MockNotificationSender()
    worker = DurableGenerationWorker(service, worker_id="serverless", sender=sender)
    assert worker.run_job_id(job.id) is True
    first_sent = list(sender.sent)
    assert worker.run_job_id(job.id) is False
    assert sender.sent == first_sent
    payment_ids = {
        t.telegram_payment_id
        for t in service.repo.transactions.values()
        if t.telegram_payment_id
    }
    assert len(payment_ids) == 1
    assert service.repo.jobs[job.id].status is JobStatus.COMPLETED


def test_expired_lease_reclaimed_by_run_job_id() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    other = service.repo.claim_queued_job("other-worker", now=job.created_at)
    assert other is not None
    job.lease_expires_at = job.created_at - timedelta(seconds=1)
    sender = MockNotificationSender()
    ok = DurableGenerationWorker(
        service, worker_id="serverless", sender=sender
    ).run_job_id(job.id)
    assert ok is True
    assert service.repo.jobs[job.id].status is JobStatus.COMPLETED
    assert sender.sent


def test_mock_worker_blocks_paid_generation() -> None:
    service, _job = _authorized_job()
    try:
        MockGenerationWorker(service, allow_paid_generation=True)
    except ProductError as exc:
        assert "ALLOW_PAID_GENERATION" in str(exc)
    else:
        raise AssertionError("paid generation must be impossible")
    try:
        MockGenerationWorker(service, generation_mode="live")
    except ProductError as exc:
        assert "GENERATION_MODE" in str(exc)
    else:
        raise AssertionError("live generation must be impossible")


def test_placeholder_storage_does_not_imply_disk() -> None:
    store = PlaceholderStorageBackend()
    key = store.put_bytes("jobs/x/still.bin", b"mock-still")
    assert store.exists(key) is False
    try:
        store.get_bytes(key)
    except KeyError:
        pass
    else:
        raise AssertionError("placeholder bytes must not be readable")
    assert store.url_for(key).startswith("placeholder://")


def test_internal_job_run_is_protected_and_bounded() -> None:
    service, job = _authorized_job()
    service.start_generation(job.user_id, job.id)
    app = create_app(
        service=service,
        env="test",
        job_execution_mode="worker",
        internal_job_secret="s3cret",
        generation_mode="mock",
        allow_paid_generation=False,
    )
    client = TestClient(app)
    assert client.post("/internal/jobs/run").status_code == 401
    denied = client.post(
        "/internal/jobs/run",
        headers={"X-Internal-Job-Secret": "wrong"},
    )
    assert denied.status_code == 401
    ok = client.post(
        "/internal/jobs/run",
        headers={"X-Internal-Job-Secret": "s3cret"},
    )
    assert ok.status_code == 200
    assert ok.json() == {"ran": 1}
    assert service.repo.jobs[job.id].status is JobStatus.COMPLETED
    again = client.post(
        "/internal/jobs/run",
        headers={"X-Internal-Job-Secret": "s3cret"},
    )
    assert again.json() == {"ran": 0}


def test_inline_generate_completes_without_dev_runner() -> None:
    from datetime import UTC, datetime

    from docprod.api.session import SessionIssuer
    from docprod.product.auth import build_init_data_query
    from docprod.product.services import ProductService

    bot = "test-bot-token"
    sender = MockNotificationSender()
    service = ProductService(bot_token=bot)
    app = create_app(
        service=service,
        env="test",
        sessions=SessionIssuer("sess"),
        job_execution_mode="inline",
        notifier=sender,
        generation_mode="mock",
        allow_paid_generation=False,
    )
    client = TestClient(app)
    query = build_init_data_query(
        bot_token=bot,
        user={"id": 88, "first_name": "Ada"},
        auth_date=int(datetime.now(UTC).timestamp()),
    )
    token = client.post("/api/v1/auth/telegram", json={"init_data": query}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    project_id = client.post(
        "/api/v1/projects",
        json={"prompt": "hello world prompt", "duration_mode": "AUTO"},
        headers=headers,
    ).json()["id"]
    plan = client.post(
        f"/api/v1/projects/{project_id}/plan", json={}, headers=headers
    ).json()
    quote = client.post(
        f"/api/v1/projects/{project_id}/quote",
        json={"plan_id": plan["plan_id"]},
        headers=headers,
    ).json()
    client.post(f"/api/v1/dev/payments/{quote['quote_id']}/confirm", headers=headers)
    gen = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"quote_id": quote["quote_id"]},
        headers=headers,
    )
    assert gen.status_code == 202
    assert gen.json()["status"] == "COMPLETED"
    assert sender.sent
    scenes = client.get(f"/api/v1/projects/{project_id}/scenes", headers=headers).json()
    image_id = scenes[0]["image_asset_version_id"]
    media = client.get(f"/api/v1/media/{image_id}", headers=headers)
    assert media.status_code == 200


def test_vercel_entrypoint_file_reuses_create_app() -> None:
    text = Path("app.py").read_text(encoding="utf-8")
    assert "app_from_settings" in text
    assert "app = app_from_settings()" in text
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'entrypoint = "app:app"' in pyproject
    assert not Path("api/index.py").exists()
    vercel = Path("vercel.json").read_text(encoding="utf-8")
    assert '"framework": "fastapi"' in vercel
    assert '"app.py"' in vercel


def test_public_api_contract_is_root_not_api_prefix() -> None:
    from fastapi.testclient import TestClient

    from docprod.api.app import create_app

    application = create_app(env="test")
    client = TestClient(application)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/api/health").status_code == 404
    assert client.get("/api/ready").status_code == 404
    assert client.get("/api/v1/models").status_code == 200
    assert client.post("/telegram/webhook", json={}).status_code == 200
    assert client.post("/internal/jobs/run").status_code == 401
    paths = application.openapi()["paths"]
    assert "/health" in paths
    assert "/ready" in paths
    assert "/telegram/webhook" in paths
    assert "/internal/jobs/run" in paths
    assert "/api/v1/models" in paths
    assert "/api/health" not in paths
    assert client.get("/docs").status_code == 200
