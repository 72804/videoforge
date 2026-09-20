from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, Request

from docprod.api.errors import api_error
from docprod.api.session import SessionIssuer
from docprod.product.errors import AuthError
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService
from docprod.product.worker import MockGenerationWorker


@dataclass
class AppContext:
    service: ProductService
    sessions: SessionIssuer
    env: str
    worker: MockGenerationWorker
    cors_origins: list[str]


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_service(request: Request) -> ProductService:
    return get_ctx(request).service


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> TelegramUser:
    ctx = get_ctx(request)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise api_error(401, "AUTH_INVALID", "Missing session token.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        user_id = ctx.sessions.parse(token, now=ctx.service.clock())
    except AuthError as exc:
        code = "AUTH_EXPIRED" if "expired" in str(exc).lower() else "AUTH_INVALID"
        raise api_error(401, code, "Invalid or expired session.") from exc
    user = ctx.service.repo.users.get(user_id)
    if user is None:
        raise api_error(401, "AUTH_INVALID", "Unknown session user.")
    return user
