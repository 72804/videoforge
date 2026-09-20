from __future__ import annotations

from typing import Any

from docprod.product.errors import QuoteError
from docprod.product.services import ProductService
from docprod.telegram.bot import handle_command
from docprod.telegram.client import TelegramClient
from docprod.telegram.payments import process_successful_payment, validate_pre_checkout


def dispatch_update(
    service: ProductService,
    telegram: TelegramClient,
    update: dict[str, Any],
    *,
    mini_app_url: str = "",
) -> None:
    """Route Telegram updates. Unknown payloads are ignored."""
    if not isinstance(update, dict):
        return
    query = update.get("pre_checkout_query")
    if isinstance(query, dict):
        _pre_checkout(service, telegram, query)
        return
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    payment = message.get("successful_payment")
    if isinstance(payment, dict):
        from_user = message.get("from") or {}
        try:
            process_successful_payment(
                service,
                payload=str(payment.get("invoice_payload") or ""),
                telegram_payment_charge_id=str(payment.get("telegram_payment_charge_id") or ""),
                stars=int(payment.get("total_amount") or 0),
                currency=str(payment.get("currency") or ""),
                telegram_user_id=int(from_user.get("id") or 0),
            )
        except QuoteError:
            return
        return
    text = str(message.get("text") or "")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if text.startswith("/") and chat_id is not None:
        handle_command(telegram, chat_id=int(chat_id), text=text, mini_app_url=mini_app_url)


def _pre_checkout(service: ProductService, telegram: TelegramClient, query: dict[str, Any]) -> None:
    query_id = str(query.get("id") or "")
    from_user = query.get("from") or {}
    ok, error = validate_pre_checkout(
        service,
        payload=str(query.get("invoice_payload") or ""),
        stars=int(query.get("total_amount") or 0),
        currency=str(query.get("currency") or ""),
        telegram_user_id=int(from_user.get("id") or 0),
    )
    try:
        telegram.answer_pre_checkout(query_id, ok=ok, error_message=error)
    except Exception:
        if not ok:
            raise QuoteError(error or "pre-checkout rejected") from None
        raise
