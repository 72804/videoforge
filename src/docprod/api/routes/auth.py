from __future__ import annotations

from fastapi import APIRouter, Request

from docprod.api.dependencies import get_ctx
from docprod.api.errors import map_product_error
from docprod.api.schemas import AuthRequest, AuthResponse, UserView
from docprod.product.errors import ProductError

router = APIRouter(tags=["auth"])


@router.post("/auth/telegram", response_model=AuthResponse, operation_id="authTelegram")
def auth_telegram(body: AuthRequest, request: Request) -> AuthResponse:
    ctx = get_ctx(request)
    try:
        user = ctx.service.authenticate_telegram(body.init_data)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    token = ctx.sessions.issue(user.id, ctx.service.clock())
    return AuthResponse(
        token=token,
        user=UserView(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            first_name=user.first_name,
            language_code=user.language_code,
        ),
    )
