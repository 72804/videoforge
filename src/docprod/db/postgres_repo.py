from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from docprod.db import mapping, orm
from docprod.db.mapping import FLUSH_ORDER, job_from_row, plan_item_rows
from docprod.product.errors import IdempotencyConflictError, JobConflictError
from docprod.product.models import (
    GenerationJob,
    IdempotencyRecord,
    StarTransaction,
    TelegramPayment,
    utcnow,
)
from docprod.product.repository import CLAIMABLE_JOB, MemoryRepository


def _snap(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, default=str)


class PostgresRepository(MemoryRepository):
    """SQLAlchemy-backed repository. Domain models stay Pydantic."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.factory = factory
        self.session: Session | None = None
        self._snapshots: dict[str, dict[str, str]] = {}

    def persistence_kind(self) -> str:
        return "postgres"

    def ping(self) -> bool:
        assert self.session is not None
        self.session.execute(select(1))
        return True

    def open(self) -> None:
        if self.session is None:
            self.session = self.factory()

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None

    @contextmanager
    def transaction(self):
        self.open()
        assert self.session is not None
        try:
            yield self
            self.flush_dirty()
        except Exception:
            self.session.rollback()
            raise

    def hydrate(self) -> None:
        assert self.session is not None
        session = self.session
        tables = {
            "users": self.users,
            "projects": self.projects,
            "characters": self.characters,
            "references": self.references,
            "scripts": self.scripts,
            "scenes": self.scenes,
            "scene_versions": self.scene_versions,
            "assets": self.assets,
            "asset_versions": self.asset_versions,
            "plans": self.plans,
            "quotes": self.quotes,
            "payments": self.payments,
            "jobs": self.jobs,
            "attempts": self.attempts,
            "renders": self.renders,
            "transactions": self.transactions,
            "outbox": self.outbox,
            "idempotency": self.idempotency,
            "workers": self.workers,
        }
        for name, _cls, _to_row, from_row in FLUSH_ORDER:
            tables[name].clear()
        for name, cls, _to_row, from_row in FLUSH_ORDER:
            for row in session.scalars(select(cls)):
                domain = from_row(row)
                if name == "idempotency":
                    key = f"{domain.user_id}:{domain.action}:{domain.key}"
                    self.idempotency[key] = domain
                elif name == "workers":
                    self.workers[domain.worker_id] = domain
                else:
                    tables[name][domain.id] = domain
        self.users_by_telegram = {
            user.telegram_user_id: user.id for user in self.users.values()
        }
        self.txn_by_idempotency = {
            txn.idempotency_key: txn.id for txn in self.transactions.values()
        }
        self.payments_by_telegram = {
            pay.telegram_payment_id: pay.id for pay in self.payments.values()
        }

    def snapshot(self) -> None:
        self._snapshots = {}
        for name, table in self._named_tables():
            self._snapshots[name] = {key: _snap(model) for key, model in table.items()}

    def _named_tables(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            ("users", self.users),
            ("projects", self.projects),
            ("characters", self.characters),
            ("references", self.references),
            ("scripts", self.scripts),
            ("scenes", self.scenes),
            ("scene_versions", self.scene_versions),
            ("assets", self.assets),
            ("asset_versions", self.asset_versions),
            ("plans", self.plans),
            ("quotes", self.quotes),
            ("payments", self.payments),
            ("jobs", self.jobs),
            ("attempts", self.attempts),
            ("renders", self.renders),
            ("transactions", self.transactions),
            ("outbox", self.outbox),
            ("idempotency", self.idempotency),
            ("workers", self.workers),
        ]

    def flush_dirty(self) -> None:
        assert self.session is not None
        session = self.session
        converters = {name: (cls, to_row) for name, cls, to_row, _from in FLUSH_ORDER}
        dirty_plans: list[Any] = []
        for name, table in self._named_tables():
            cls, to_row = converters[name]
            previous = self._snapshots.get(name, {})
            for key, model in table.items():
                current = _snap(model)
                if previous.get(key) == current:
                    continue
                session.merge(to_row(model))
                if name == "plans":
                    dirty_plans.append(model)
            for key in previous:
                if key not in table:
                    if name == "workers":
                        session.execute(
                            delete(orm.WorkerHeartbeatRow).where(
                                orm.WorkerHeartbeatRow.worker_id == key
                            )
                        )
                    elif name == "idempotency":
                        continue
                    else:
                        session.execute(delete(cls).where(cls.id == key))
            session.flush()
        if dirty_plans:
            ids = [plan.id for plan in dirty_plans]
            session.execute(
                delete(orm.GenerationPlanItemRow).where(
                    orm.GenerationPlanItemRow.plan_id.in_(ids)
                )
            )
            for plan in dirty_plans:
                for item in plan_item_rows(plan):
                    session.add(item)
        session.flush()

    def commit(self) -> None:
        assert self.session is not None
        self.flush_dirty()
        self.session.commit()
        self.snapshot()

    def rollback(self) -> None:
        if self.session is not None:
            self.session.rollback()

    def put_payment(self, payment: TelegramPayment) -> TelegramPayment:
        if self.session is None:
            return super().put_payment(payment)
        self.flush_dirty()
        existing_id = self.payments_by_telegram.get(payment.telegram_payment_id)
        if existing_id:
            return self.payments[existing_id]
        try:
            with self.session.begin_nested():
                self.session.add(mapping.payment_to_row(payment))
                self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != "23505":
                raise
            row = self.session.scalars(
                select(orm.TelegramPaymentRow).where(
                    orm.TelegramPaymentRow.telegram_payment_id == payment.telegram_payment_id
                )
            ).one()
            stored = mapping.payment_from_row(row)
            self.payments[stored.id] = stored
            self.payments_by_telegram[stored.telegram_payment_id] = stored.id
            return stored
        self.payments[payment.id] = payment
        self.payments_by_telegram[payment.telegram_payment_id] = payment.id
        return payment

    def put_transaction(self, txn: StarTransaction) -> StarTransaction:
        if self.session is None:
            return super().put_transaction(txn)
        self.flush_dirty()
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
        try:
            with self.session.begin_nested():
                self.session.add(mapping.txn_to_row(txn))
                self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != "23505":
                raise
            row = self.session.scalars(
                select(orm.StarTransactionRow).where(
                    orm.StarTransactionRow.idempotency_key == txn.idempotency_key
                )
            ).one()
            stored = mapping.txn_from_row(row)
            self.transactions[stored.id] = stored
            self.txn_by_idempotency[stored.idempotency_key] = stored.id
            return stored
        self.transactions[txn.id] = txn
        self.txn_by_idempotency[txn.idempotency_key] = txn.id
        return txn

    def put_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        if self.session is None:
            return super().put_idempotency(record)
        self.flush_dirty()
        slot = f"{record.user_id}:{record.action}:{record.key}"
        existing = self.idempotency.get(slot)
        if existing:
            if existing.request_hash != record.request_hash:
                raise IdempotencyConflictError("idempotency key reused with different payload")
            return existing
        try:
            with self.session.begin_nested():
                self.session.add(mapping.idem_to_row(record))
                self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != "23505":
                raise
            row = self.session.scalars(
                select(orm.IdempotencyRecordRow).where(
                    orm.IdempotencyRecordRow.user_id == record.user_id,
                    orm.IdempotencyRecordRow.action == record.action,
                    orm.IdempotencyRecordRow.idempotency_key == record.key,
                )
            ).one()
            stored = mapping.idem_from_row(row)
            if stored.request_hash != record.request_hash:
                raise IdempotencyConflictError("idempotency key reused with different payload")
            self.idempotency[slot] = stored
            return stored
        self.idempotency[slot] = record
        return record

    def claim_queued_job(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease: timedelta = timedelta(seconds=30),
    ) -> GenerationJob | None:
        if self.session is None:
            return super().claim_queued_job(worker_id, now=now, lease=lease)
        stamp = now or utcnow()
        stmt = (
            select(orm.GenerationJobRow)
            .where(orm.GenerationJobRow.status.in_([status.value for status in CLAIMABLE_JOB]))
            .where(
                or_(
                    orm.GenerationJobRow.claimed_by.is_(None),
                    orm.GenerationJobRow.lease_expires_at.is_(None),
                    orm.GenerationJobRow.lease_expires_at <= stamp,
                )
            )
            .order_by(orm.GenerationJobRow.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        row = self.session.scalars(stmt).first()
        if row is None:
            return None
        row.claimed_by = worker_id
        row.claimed_at = stamp
        row.heartbeat_at = stamp
        row.lease_expires_at = stamp + lease
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.updated_at = stamp
        self.session.flush()
        job = job_from_row(row)
        self.jobs[job.id] = job
        return job

    def heartbeat_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease: timedelta = timedelta(seconds=30),
    ) -> GenerationJob:
        if self.session is None:
            return super().heartbeat_job(job_id, worker_id, now=now, lease=lease)
        stamp = now or utcnow()
        job = self.jobs[job_id]
        if job.claimed_by != worker_id:
            raise JobConflictError("job lease owned by another worker")
        job.heartbeat_at = stamp
        job.lease_expires_at = stamp + lease
        job.updated_at = stamp
        row = self.session.get(orm.GenerationJobRow, job_id)
        if row is not None:
            if row.claimed_by != worker_id:
                raise JobConflictError("job lease owned by another worker")
            row.heartbeat_at = stamp
            row.lease_expires_at = stamp + lease
            row.updated_at = stamp
            self.session.flush()
        return job

    def import_memory(self, other: MemoryRepository) -> None:
        dump = other.__dict__
        for name, table in self._named_tables():
            table.clear()
            source = dump[name]
            table.update(source)
        self.users_by_telegram = dict(other.users_by_telegram)
        self.txn_by_idempotency = dict(other.txn_by_idempotency)
        self.payments_by_telegram = dict(other.payments_by_telegram)
        self._snapshots = {}
        self.flush_dirty()
        assert self.session is not None
        self.session.commit()
        self.hydrate()
        self.snapshot()
