from __future__ import annotations

from docprod.product.enums import PaymentIntentStatus, QuoteStatus
from docprod.product.errors import OwnershipError, QuoteError
from docprod.product.models import PaymentIntent, StarQuote
from docprod.product.services import ProductService
from docprod.telegram.client import TelegramClient


def _assert_quote_payable(service: ProductService, user_id: str, quote: StarQuote) -> None:
    if quote.user_id != user_id:
        raise OwnershipError("quote does not belong to user")
    service._expire_quote(quote)
    if quote.status is QuoteStatus.EXPIRED:
        raise QuoteError("quote expired")
    if quote.status in {QuoteStatus.AUTHORIZED, QuoteStatus.CONSUMED}:
        raise QuoteError("quote already paid")
    if quote.status is not QuoteStatus.OPEN:
        raise QuoteError("quote is not payable")
    plan = service.repo.plans.get(quote.generation_plan_id)
    if plan is None or plan.plan_hash != quote.generation_plan_hash:
        raise QuoteError("plan changed after quote; requote")


def create_stars_invoice(
    service: ProductService,
    user_id: str,
    quote_id: str,
    telegram: TelegramClient,
) -> PaymentIntent:
    quote = service.repo.quotes.get(quote_id)
    if quote is None:
        raise QuoteError("quote not found")
    _assert_quote_payable(service, user_id, quote)
    for intent in service.repo.intents.values():
        if intent.quote_id == quote_id and intent.status is PaymentIntentStatus.OPEN:
            if intent.invoice_url:
                return intent
    intent = PaymentIntent(
        user_id=user_id,
        quote_id=quote.id,
        project_id=quote.project_id,
        plan_hash=quote.generation_plan_hash,
        stars=quote.stars,
        created_at=service.clock(),
    )
    url = telegram.create_invoice_link(
        title="Docprod video",
        description="AI video generation",
        payload=intent.id,
        stars=quote.stars,
    )
    intent.invoice_url = url
    intent.status = PaymentIntentStatus.PENDING
    service.repo.intents[intent.id] = intent
    return intent


def customer_payment_status(service: ProductService, user_id: str, quote_id: str) -> str:
    quote = service.repo.quotes.get(quote_id)
    if quote is None:
        raise QuoteError("quote not found")
    if quote.user_id != user_id:
        raise OwnershipError("quote does not belong to user")
    service._expire_quote(quote)
    if quote.status in {QuoteStatus.AUTHORIZED, QuoteStatus.CONSUMED}:
        payment = service.payment_for_quote(quote_id)
        if payment and payment.refund_status == "REFUNDED":
            return "REFUNDED"
        return "PAID"
    if quote.status is QuoteStatus.EXPIRED:
        return "EXPIRED"
    for intent in service.repo.intents.values():
        if intent.quote_id == quote_id and intent.status is PaymentIntentStatus.PENDING:
            return "PENDING"
    return "UNPAID"


def validate_pre_checkout(
    service: ProductService,
    *,
    payload: str,
    stars: int,
    currency: str,
    telegram_user_id: int,
) -> tuple[bool, str]:
    if currency != "XTR":
        return False, "Unsupported currency."
    intent = service.repo.intents.get(payload)
    if intent is None:
        return False, "Unknown payment."
    quote = service.repo.quotes.get(intent.quote_id)
    if quote is None:
        return False, "Unknown quote."
    user = service.repo.user_by_telegram(telegram_user_id)
    if user is None or user.id != intent.user_id or quote.user_id != intent.user_id:
        return False, "This payment is not yours."
    service._expire_quote(quote)
    if quote.status is QuoteStatus.EXPIRED:
        intent.status = PaymentIntentStatus.EXPIRED
        return False, "This price expired."
    if quote.status in {QuoteStatus.AUTHORIZED, QuoteStatus.CONSUMED}:
        return False, "Already paid."
    if intent.stars != quote.stars or stars != quote.stars:
        return False, "Amount does not match."
    if quote.generation_plan_hash != intent.plan_hash:
        return False, "The plan changed. Recalculate the price."
    return True, ""


def process_successful_payment(
    service: ProductService,
    *,
    payload: str,
    telegram_payment_charge_id: str,
    stars: int,
    currency: str,
    telegram_user_id: int,
) -> None:
    if not telegram_payment_charge_id:
        raise QuoteError("missing telegram payment id")
    existing = service.repo.payments_by_telegram.get(telegram_payment_charge_id)
    if existing:
        return
    intent = service.repo.intents.get(payload)
    if intent is not None and intent.telegram_payment_charge_id == telegram_payment_charge_id:
        return
    ok, message = validate_pre_checkout(
        service,
        payload=payload,
        stars=stars,
        currency=currency,
        telegram_user_id=telegram_user_id,
    )
    if intent is None:
        return
    if not ok:
        if message == "Already paid.":
            return
        raise QuoteError(message or "payment rejected")
    user = service.repo.users[intent.user_id]
    service.confirm_telegram_payment(
        user.id,
        quote_id=intent.quote_id,
        telegram_payment_id=telegram_payment_charge_id,
        stars=stars,
        invoice_payload=payload,
    )
    intent.status = PaymentIntentStatus.PAID
    intent.telegram_payment_charge_id = telegram_payment_charge_id
