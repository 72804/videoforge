from __future__ import annotations

import signal
import socket
import time
from datetime import timedelta

from docprod.db.postgres_repo import PostgresRepository
from docprod.logging_utils import get_logger
from docprod.observability import log_scope
from docprod.product.models import WorkerHeartbeat, utcnow
from docprod.product.notifications import MockNotificationSender, drain_outbox
from docprod.product.services import ProductService
from docprod.product.worker import MockGenerationWorker

log = get_logger("product.durable_worker")


class DurableGenerationWorker:
    def __init__(
        self,
        service: ProductService,
        *,
        worker_id: str,
        poll_seconds: float = 1.0,
        lease_seconds: int = 30,
        sender: MockNotificationSender | None = None,
        generation_mode: str = "mock",
        allow_paid_generation: bool = False,
    ) -> None:
        self.service = service
        self.worker_id = worker_id
        self.poll_seconds = max(poll_seconds, 0.05)
        self.lease = timedelta(seconds=lease_seconds)
        self.sender = sender or MockNotificationSender()
        self.mock = MockGenerationWorker(
            service,
            worker_id=worker_id,
            generation_mode=generation_mode,
            allow_paid_generation=allow_paid_generation,
        )
        self.mock.lease = self.lease
        self.stop = False

    def request_stop(self, *_args: object) -> None:
        self.stop = True

    def install_signals(self) -> None:
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

    def _beat(self, job_id: str | None = None) -> None:
        self.service.repo.put_worker_heartbeat(
            WorkerHeartbeat(
                worker_id=self.worker_id,
                hostname=socket.gethostname(),
                last_seen_at=utcnow(),
                current_job_id=job_id,
            )
        )

    def _with_unit(self, fn):
        repo = self.service.repo
        if isinstance(repo, PostgresRepository):
            repo.open()
            try:
                repo.hydrate()
                repo.snapshot()
                result = fn()
                repo.commit()
                return result
            except Exception:
                repo.rollback()
                raise
            finally:
                repo.close()
        return fn()

    def tick(self) -> bool:
        def _once() -> bool:
            self._beat()
            job = self.service.repo.claim_queued_job(
                self.worker_id, now=utcnow(), lease=self.lease
            )
            drain_outbox(self.service.repo, self.sender)
            if job is None:
                return False
            with log_scope(job_id=job.id, user_id=job.user_id, project_id=job.project_id):
                log.info("claimed generation job")
                self._beat(job.id)
                try:
                    self.mock.run_job(job.id)
                except Exception:
                    log.exception("worker job failed")
                    try:
                        self.service.fail_job(
                            job.id,
                            public_message="Generation failed.",
                            error_code="WORKER_FAILURE",
                        )
                    except Exception:
                        log.exception("could not persist safe job failure")
            drain_outbox(self.service.repo, self.sender)
            self._beat(None)
            return True

        return bool(self._with_unit(_once))

    def run_forever(self) -> None:
        self.install_signals()
        log.info("durable worker starting")
        while not self.stop:
            worked = self.tick()
            if not worked and not self.stop:
                time.sleep(self.poll_seconds)
        log.info("durable worker stopped")
