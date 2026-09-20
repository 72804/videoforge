from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from docprod.api.dependencies import current_user, get_ctx
from docprod.api.errors import api_error, map_product_error
from docprod.api.idempotency import lookup, remember
from docprod.api.schemas import AuthResponse, DevAuthRequest, QuoteView, UserView
from docprod.product.errors import ProductError
from docprod.product.models import TelegramUser

router = APIRouter(tags=["dev-payments"])


@router.post("/dev/auth", response_model=AuthResponse, operation_id="devAuth")
def dev_auth(body: DevAuthRequest, request: Request) -> AuthResponse:
    ctx = get_ctx(request)
    if ctx.env not in {"development", "test"}:
        raise api_error(404, "NOT_FOUND", "Not found.")
    saved = ctx.service.repo.put_user(
        TelegramUser(telegram_user_id=body.telegram_user_id, first_name=body.first_name)
    )
    token = ctx.sessions.issue(saved.id, ctx.service.clock())
    return AuthResponse(
        token=token,
        user=UserView(
            id=saved.id,
            telegram_user_id=saved.telegram_user_id,
            username=saved.username,
            first_name=saved.first_name,
            language_code=saved.language_code,
        ),
    )


@router.post(
    "/dev/payments/{quote_id}/confirm",
    response_model=QuoteView,
    operation_id="devConfirmPayment",
)
def confirm_dev_payment(
    quote_id: str,
    request: Request,
    user: TelegramUser = Depends(current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> QuoteView:
    ctx = get_ctx(request)
    if ctx.env not in {"development", "test"}:
        raise api_error(404, "NOT_FOUND", "Not found.")
    payload = {"quote_id": quote_id}
    try:
        hit = lookup(
            ctx.service,
            user_id=user.id,
            action="dev-payment",
            key=idempotency_key,
            payload=payload,
        )
        if hit:
            return QuoteView.model_validate(hit.body)
        quote = ctx.service.repo.quotes.get(quote_id)
        if quote is None:
            raise api_error(404, "NOT_FOUND", "quote not found")
        ctx.service.confirm_telegram_payment(
            user.id,
            quote_id=quote_id,
            telegram_payment_id=f"sim:{quote_id}",
            stars=quote.stars,
            invoice_payload="DEVELOPMENT_SIMULATED_PAYMENT",
        )
        quote = ctx.service.repo.quotes[quote_id]
    except ProductError as exc:
        raise map_product_error(exc) from exc
    view = QuoteView(
        quote_id=quote.id,
        plan_hash=quote.generation_plan_hash,
        stars=quote.stars,
        expires_at=quote.expires_at.isoformat(),
        status=quote.status.value,
        simulated=True,
    )
    remember(
        ctx.service,
        user_id=user.id,
        action="dev-payment",
        key=idempotency_key,
        payload=payload,
        status_code=200,
        body=view.model_dump(),
    )
    return view
