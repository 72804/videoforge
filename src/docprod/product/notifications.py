from __future__ import annotations

from docprod.product.enums import OutboxStatus
from docprod.product.models import NotificationOutbox, utcnow
from docprod.product.repository import MemoryRepository


class NotificationSender:
    def send(self, note: NotificationOutbox) -> None:
        raise NotImplementedError


class MockNotificationSender(NotificationSender):
    """Records deliveries. Never calls Telegram."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, note: NotificationOutbox) -> None:
        self.sent.append(note.id)


def drain_outbox(
    repo: MemoryRepository,
    sender: NotificationSender,
    *,
    now=None,
) -> int:
    stamp = now or utcnow()
    delivered = 0
    for note in repo.pending_outbox(stamp):
        sender.send(note)
        note.status = OutboxStatus.SENT
        note.sent_at = stamp
        note.attempts += 1
        repo.put_outbox(note)
        delivered += 1
    return delivered
