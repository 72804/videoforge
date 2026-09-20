from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class TelegramAPIError(RuntimeError):
    """Bot API call failed. Never include the bot token in the message."""


class TelegramClient(Protocol):
    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def create_invoice_link(
        self,
        *,
        title: str,
        description: str,
        payload: str,
        stars: int,
    ) -> str: ...

    def answer_pre_checkout(self, query_id: str, *, ok: bool, error_message: str = "") -> None: ...

    def set_webhook(
        self,
        url: str,
        *,
        secret_token: str = "",
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def webhook_info(self) -> dict[str, Any]: ...

    def get_updates(self, offset: int = 0, timeout: int = 20) -> list[dict[str, Any]]: ...

    def refund_star_payment(
        self, user_id: int, telegram_payment_charge_id: str
    ) -> dict[str, Any]: ...


class HttpxTelegramClient:
    """Official Bot HTTP API. Stars invoices use currency XTR and an empty provider token."""

    def __init__(self, bot_token: str, *, timeout: float = 20.0) -> None:
        if not bot_token.strip():
            raise TelegramAPIError("bot token is not configured")
        self._base = f"https://api.telegram.org/bot{bot_token.strip()}"
        self._timeout = timeout

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        try:
            response = httpx.post(
                f"{self._base}/{method}",
                json=payload or {},
                timeout=timeout if timeout is not None else self._timeout,
            )
        except httpx.HTTPError as exc:
            raise TelegramAPIError("telegram request failed") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramAPIError("telegram returned non-json") from exc
        if not body.get("ok"):
            raise TelegramAPIError(str(body.get("description") or "telegram error"))
        return body.get("result")

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def create_invoice_link(
        self,
        *,
        title: str,
        description: str,
        payload: str,
        stars: int,
    ) -> str:
        result = self._call(
            "createInvoiceLink",
            {
                "title": title[:32],
                "description": description[:255],
                "payload": payload[:128],
                "provider_token": "",
                "currency": "XTR",
                "prices": [{"label": "Video", "amount": int(stars)}],
            },
        )
        return str(result)

    def answer_pre_checkout(self, query_id: str, *, ok: bool, error_message: str = "") -> None:
        payload: dict[str, Any] = {"pre_checkout_query_id": query_id, "ok": ok}
        if not ok and error_message:
            payload["error_message"] = error_message[:200]
        self._call("answerPreCheckoutQuery", payload)

    def set_webhook(
        self,
        url: str,
        *,
        secret_token: str = "",
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]:
        if not url.strip():
            return self._call("deleteWebhook", {"drop_pending_updates": False})
        payload: dict[str, Any] = {
            "url": url,
            "allowed_updates": allowed_updates
            or ["message", "pre_checkout_query"],
            "drop_pending_updates": False,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        return self._call("setWebhook", payload)

    def webhook_info(self) -> dict[str, Any]:
        return self._call("getWebhookInfo", {})

    def get_updates(self, offset: int = 0, timeout: int = 20) -> list[dict[str, Any]]:
        result = self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout},
            timeout=float(timeout) + 5.0,
        )
        return list(result or [])

    def refund_star_payment(self, user_id: int, telegram_payment_charge_id: str) -> dict[str, Any]:
        return self._call(
            "refundStarPayment",
            {"user_id": user_id, "telegram_payment_charge_id": telegram_payment_charge_id},
        )


@dataclass
class FakeTelegramClient:
    """In-memory Telegram for tests. Never contacts Telegram. Never spends Stars."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    invoices: list[dict[str, Any]] = field(default_factory=list)
    pre_checkouts: list[dict[str, Any]] = field(default_factory=list)
    refunds: list[dict[str, Any]] = field(default_factory=list)
    webhook: dict[str, Any] = field(default_factory=dict)
    fail_send: bool = False

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.fail_send:
            raise TelegramAPIError("transient telegram failure")
        row = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        self.messages.append(row)
        return row

    def create_invoice_link(
        self,
        *,
        title: str,
        description: str,
        payload: str,
        stars: int,
    ) -> str:
        self.invoices.append(
            {
                "title": title,
                "description": description,
                "payload": payload,
                "stars": stars,
                "currency": "XTR",
            }
        )
        return f"https://t.me/$fake-invoice/{payload}"

    def answer_pre_checkout(self, query_id: str, *, ok: bool, error_message: str = "") -> None:
        self.pre_checkouts.append({"id": query_id, "ok": ok, "error_message": error_message})

    def set_webhook(
        self,
        url: str,
        *,
        secret_token: str = "",
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]:
        self.webhook = {
            "url": url,
            "has_custom_certificate": False,
            "pending_update_count": 0,
            "allowed_updates": allowed_updates,
            "secret_configured": bool(secret_token),
        }
        return self.webhook

    def webhook_info(self) -> dict[str, Any]:
        return dict(self.webhook)

    def get_updates(self, offset: int = 0, timeout: int = 20) -> list[dict[str, Any]]:
        return []

    def refund_star_payment(self, user_id: int, telegram_payment_charge_id: str) -> dict[str, Any]:
        row = {"user_id": user_id, "telegram_payment_charge_id": telegram_payment_charge_id}
        self.refunds.append(row)
        return {"ok": True, **row}
