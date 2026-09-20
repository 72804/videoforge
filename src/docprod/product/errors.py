from __future__ import annotations


class ProductError(RuntimeError):
    """Base error for Telegram product services."""


class AuthError(ProductError):
    """Telegram Mini App initData failed validation."""


class OwnershipError(ProductError):
    """Caller does not own the requested resource."""


class LimitExceededError(ProductError):
    """A ProductLimits check failed."""


class QuoteError(ProductError):
    """Star quote is missing, expired, or does not match the generation plan."""


class AuthorizationError(ProductError):
    """Paid generation is not authorized."""


class JobStateError(ProductError):
    """Illegal generation-job state transition."""


class IdempotencyConflictError(ProductError):
    """Idempotency key reused with a different payload."""


class NotFoundError(ProductError):
    """Resource does not exist."""


class SceneLockedError(ProductError):
    """Scene is locked against automatic or implicit mutation."""


class JobConflictError(ProductError):
    """An overlapping generation job is already active."""


class UploadError(ProductError):
    """Uploaded file failed validation."""
