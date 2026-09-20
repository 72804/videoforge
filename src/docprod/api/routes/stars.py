from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from docprod.api.dependencies import current_user, get_ctx
from docprod.api.errors import api_error, map_product_error
from docprod.product.errors import ProductError
from docprod.product.models import TelegramUser
from docprod.telegram.payments import create_stars_invoice, customer_payment_status

router = APIRouter(tags=["payments"])


@router.post("/quotes/{quote_id}/telegram-invoice", operation_id="createTelegramInvoice")
def create_invoice(
    quote_id: str,
    request: Request,
    user: TelegramUser = Depends(current_user),
) -> dict:
    ctx = get_ctx(request)
    if ctx.payment_mode not in {"telegram", "fake"}:
        raise api_error(404, "NOT_FOUND", "Not found.")
    try:
        intent = create_stars_invoice(ctx.service, user.id, quote_id, ctx.telegram)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {
        "invoice_url": intent.invoice_url,
        "quote_id": quote_id,
        "stars": intent.stars,
        "currency": "XTR",
        "simulated": False,
    }


@router.get("/quotes/{quote_id}/payment-status", operation_id="quotePaymentStatus")
def payment_status(
    quote_id: str,
    request: Request,
    user: TelegramUser = Depends(current_user),
) -> dict:
    ctx = get_ctx(request)
    try:
        status = customer_payment_status(ctx.service, user.id, quote_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"quote_id": quote_id, "status": status}
