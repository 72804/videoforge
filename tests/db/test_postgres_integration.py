from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from docprod.db.orm import Base
from docprod.db.postgres_repo import PostgresRepository
from docprod.product.durable import DurableGenerationWorker
from docprod.product.enums import JobStatus, StarTxnType
from docprod.product.errors import IdempotencyConflictError
from docprod.product.models import (
    GenerationJob,
    IdempotencyRecord,
    Project,
    TelegramUser,
    utcnow,
)
from docprod.product.services import ProductService

DEFAULT_URL = "postgresql+psycopg://docprod:docprod@127.0.0.1:5432/docprod"


def _candidates() -> list[str]:
    rows = [
        os.environ.get("TEST_DATABASE_URL"),
        os.environ.get("DATABASE_URL"),
        DEFAULT_URL,
        f"postgresql+psycopg://{os.environ.get('USER', 'docprod')}@127.0.0.1:5432/docprod_test",
    ]
    return [item for item in rows if item]


def _connects(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _url() -> str:
    for candidate in _candidates():
        if _connects(candidate):
            return candidate
    return _candidates()[0]


def postgres_available() -> bool:
    return any(_connects(candidate) for candidate in _candidates())


pytestmark = pytest.mark.skipif(not postgres_available(), reason="PostgreSQL not available")


@pytest.fixture
def pg_factory() -> Iterator[sessionmaker]:
    url = _url()
    engine = create_engine(url, future=True, poolclass=NullPool)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)
    yield factory
    with engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        conn.commit()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_alembic_upgrade_head(monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic import command
    from alembic.config import Config

    url = _url()
    engine = create_engine(url, future=True)
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")


def test_repository_crud_and_ownership(pg_factory: sessionmaker) -> None:
    repo = PostgresRepository(pg_factory)
    repo.open()
    repo.hydrate()
    repo.snapshot()
    user = repo.put_user(TelegramUser(telegram_user_id=101, first_name="Ada"))
    other = repo.put_user(TelegramUser(telegram_user_id=202, first_name="Bob"))
    project = repo.put_project(Project(user_id=user.id, title="Mine", prompt="a cinematic prompt"))
    repo.commit()
    repo.hydrate()
    assert repo.user_by_telegram(101) is not None
    assert [p.id for p in repo.projects_for(user.id)] == [project.id]
    assert repo.projects_for(other.id) == []
    repo.close()


def test_idempotency_unique_hash_conflict(pg_factory: sessionmaker) -> None:
    repo = PostgresRepository(pg_factory)
    repo.open()
    user = repo.put_user(TelegramUser(telegram_user_id=404, first_name="Ada"))
    repo.flush_dirty()
    repo.session.commit()
    repo.put_idempotency(
        IdempotencyRecord(
            key="gen",
            user_id=user.id,
            action="generate",
            request_hash="aaa",
            status_code=202,
            body={"job_id": "j"},
        )
    )
    repo.session.commit()
    other = PostgresRepository(pg_factory)
    other.open()
    other.hydrate()
    with pytest.raises(IdempotencyConflictError):
        other.put_idempotency(
            IdempotencyRecord(
                key="gen",
                user_id=user.id,
                action="generate",
                request_hash="bbb",
                status_code=202,
                body={"job_id": "other"},
            )
        )
    repo.close()
    other.close()


def test_concurrent_job_claim(pg_factory: sessionmaker) -> None:
    setup = PostgresRepository(pg_factory)
    setup.open()
    user = setup.put_user(TelegramUser(telegram_user_id=505, first_name="Ada"))
    project = setup.put_project(Project(user_id=user.id, title="P", prompt="prompt text"))
    job = GenerationJob(
        project_id=project.id,
        user_id=user.id,
        plan_hash="h",
        status=JobStatus.QUEUED,
        authorized=True,
    )
    setup.jobs[job.id] = job
    setup.commit()
    setup.close()
    left = PostgresRepository(pg_factory)
    right = PostgresRepository(pg_factory)
    left.open()
    right.open()
    one = left.claim_queued_job("worker-a", lease=timedelta(seconds=30))
    two = right.claim_queued_job("worker-b", lease=timedelta(seconds=30))
    left.commit()
    right.commit()
    left.close()
    right.close()
    winners = [row for row in (one, two) if row is not None]
    assert len(winners) == 1
    assert winners[0].id == job.id


def test_expired_lease_skip_locked_recovery(pg_factory: sessionmaker) -> None:
    setup = PostgresRepository(pg_factory)
    setup.open()
    user = setup.put_user(TelegramUser(telegram_user_id=606, first_name="Ada"))
    project = setup.put_project(Project(user_id=user.id, title="P", prompt="prompt text"))
    job = GenerationJob(
        project_id=project.id,
        user_id=user.id,
        plan_hash="h",
        status=JobStatus.GENERATING_VIDEO,
        authorized=True,
        claimed_by="dead-worker",
        claimed_at=utcnow() - timedelta(minutes=10),
        lease_expires_at=utcnow() - timedelta(seconds=1),
    )
    setup.jobs[job.id] = job
    setup.commit()
    setup.close()
    worker = PostgresRepository(pg_factory)
    worker.open()
    claimed = worker.claim_queued_job("alive", lease=timedelta(seconds=30))
    worker.commit()
    worker.close()
    assert claimed is not None
    assert claimed.claimed_by == "alive"


def test_payment_replay_worker_and_restart(pg_factory: sessionmaker) -> None:
    setup = PostgresRepository(pg_factory)
    setup.open()
    setup.hydrate()
    setup.snapshot()
    svc = ProductService(setup)
    user = svc.repo.put_user(TelegramUser(telegram_user_id=707, first_name="Ada"))
    project = svc.create_project(user.id, title="P", prompt="prompt text")
    svc.add_scene(user.id, project.id, visual_prompt="wide")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    first = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="tg-race", stars=quote.stars
    )
    second = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="tg-race", stars=quote.stars
    )
    assert first.id == second.id
    setup.commit()
    job = svc.queue_generation(user.id, project.id, quote.id)
    setup.commit()
    setup.close()

    worker_repo = PostgresRepository(pg_factory)
    worker_repo.open()
    worker_repo.hydrate()
    worker_repo.snapshot()
    worker_svc = ProductService(worker_repo)
    DurableGenerationWorker(worker_svc, worker_id="w1", poll_seconds=0.05).tick()
    worker_repo.open()
    worker_repo.hydrate()
    stored_live = worker_repo.jobs[job.id]
    worker_repo.close()

    restarted = PostgresRepository(pg_factory)
    restarted.open()
    restarted.hydrate()
    stored = restarted.jobs[job.id]
    assert stored.status is JobStatus.COMPLETED, stored.status
    assert stored_live.status is JobStatus.COMPLETED
    pays = [p for p in restarted.payments.values() if p.telegram_payment_id == "tg-race"]
    purchases = [
        t
        for t in restarted.transactions.values()
        if t.telegram_payment_id == "tg-race" and t.type is StarTxnType.PURCHASE
    ]
    assert len(pays) == 1
    assert len(purchases) == 1
    assert [n for n in restarted.outbox.values() if n.job_id == job.id]
    assert restarted.projects[project.id].title == "P"
    restarted.close()
