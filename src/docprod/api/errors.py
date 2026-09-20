from __future__ import annotations

from fastapi import HTTPException

from docprod.api.schemas import ErrorBody, ErrorResponse
from docprod.product.errors import (
    AuthError,
    AuthorizationError,
    IdempotencyConflictError,
    JobConflictError,
    LimitExceededError,
    NotFoundError,
    OwnershipError,
    ProductError,
    QuoteError,
    SceneLockedError,
    UploadError,
)


def api_error(
    status: int, code: str, message: str, details: dict | None = None
) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or {})
    )
    return HTTPException(status_code=status, detail=body.model_dump())


def map_product_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthError):
        code = "AUTH_EXPIRED" if "expired" in str(exc).lower() else "AUTH_INVALID"
        return api_error(401, code, str(exc) or "Authentication failed.")
    if isinstance(exc, OwnershipError):
        return api_error(403, "FORBIDDEN", "You do not have access to this resource.")
    if isinstance(exc, NotFoundError):
        return api_error(404, "NOT_FOUND", str(exc) or "Not found.")
    if isinstance(exc, LimitExceededError):
        return api_error(400, "LIMIT_EXCEEDED", str(exc) or "Limit exceeded.")
    if isinstance(exc, QuoteError):
        text = str(exc)
        if "expired" in text.lower():
            return api_error(400, "QUOTE_EXPIRED", "This generation quote has expired.")
        if "requote" in text.lower() or "changed" in text.lower():
            return api_error(409, "PLAN_STALE", "The generation plan is no longer current.")
        return api_error(400, "PLAN_STALE", text)
    if isinstance(exc, AuthorizationError):
        return api_error(402, "PAYMENT_REQUIRED", str(exc) or "Payment is required.")
    if isinstance(exc, JobConflictError):
        return api_error(409, "JOB_CONFLICT", str(exc) or "A job is already active.")
    if isinstance(exc, SceneLockedError):
        return api_error(409, "SCENE_LOCKED", str(exc) or "Scene is locked.")
    if isinstance(exc, UploadError):
        return api_error(400, "INVALID_UPLOAD", str(exc) or "Invalid upload.")
    if isinstance(exc, IdempotencyConflictError):
        return api_error(
            409,
            "IDEMPOTENCY_CONFLICT",
            "Idempotency key reused with a different request.",
        )
    if isinstance(exc, ProductError):
        return api_error(400, "INVALID_PROJECT", str(exc))
    return api_error(500, "INTERNAL", "Unexpected error.")
