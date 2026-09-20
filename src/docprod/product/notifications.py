from __future__ import annotations

from datetime import timedelta

from docprod.product.enums import OutboxStatus
from docprod.product.models import NotificationOutbox, utcnow
from docprod.product.repository import MemoryRepository
from docprod.telegram.bot import project_keyboard
from docprod.telegram.client import TelegramAPIError, TelegramClient


class NotificationSender:
    def send(self, note: NotificationOutbox) -> None:
        raise NotImplementedError


class MockNotificationSender(NotificationSender):
    """Records deliveries. Never calls Telegram."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, note: NotificationOutbox) -> None:
        self.sent.append(note.id)


class TelegramNotificationSender(NotificationSender):
    def __init__(self, telegram: TelegramClient, *, mini_app_url: str = "") -> None:
        self.telegram = telegram
        self.mini_app_url = mini_app_url
        self.repo = None

    def bind(self, repo: MemoryRepository) -> None:
        self.repo = repo

    def send(self, note: NotificationOutbox) -> None:
        repo = getattr(self, "repo", None)
        if repo is None:
            raise TelegramAPIError("notification sender is not bound")
        user = repo.users.get(note.user_id)
        if user is None:
            return
        if note.kind in {"project_ready", "GENERATION_COMPLETED"}:
            text = "Your video is ready 🎬"
        elif note.kind in {"generation_failed", "GENERATION_FAILED"}:
            text = "We couldn't complete your video."
        else:
            text = "Your studio has an update."
        self.telegram.send_message(
            user.telegram_user_id,
            text,
            reply_markup=project_keyboard(self.mini_app_url, note.project_id),
        )


def drain_outbox(
    repo: MemoryRepository,
    sender: NotificationSender,
    *,
    now=None,
    max_attempts: int = 8,
) -> int:
    stamp = now or utcnow()
    if isinstance(sender, TelegramNotificationSender):
        sender.bind(repo)
    delivered = 0
    for note in repo.pending_outbox(stamp):
        try:
            sender.send(note)
        except TelegramAPIError:
            note.attempts += 1
            if note.attempts >= max_attempts:
                note.status = OutboxStatus.FAILED
            else:
                note.next_attempt_at = stamp + timedelta(seconds=min(300, 2**note.attempts))
            repo.put_outbox(note)
            continue
        note.status = OutboxStatus.SENT
        note.sent_at = stamp
        note.attempts += 1
        repo.put_outbox(note)
        delivered += 1
    return delivered
