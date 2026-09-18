class PaidApiDisabledError(RuntimeError):
    """Raised when a paid provider is requested while ALLOW_PAID_APIS is false."""


class PaidApiNotConfirmedError(RuntimeError):
    """Raised when a paid call is attempted without an explicit --confirm-paid flag."""


class MissingApiKeyError(RuntimeError):
    """Raised when a required provider API key is not configured."""


class MaxPaidRequestsExceededError(RuntimeError):
    """Raised when a batch would exceed the explicit paid-request cap."""


class UnsafeProjectIdError(ValueError):
    """Raised when a project id would escape the projects root or is not filesystem-safe."""
