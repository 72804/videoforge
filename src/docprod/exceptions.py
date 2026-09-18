class PaidApiDisabledError(RuntimeError):
    """Raised when a paid provider is requested while ALLOW_PAID_APIS is false."""


class UnsafeProjectIdError(ValueError):
    """Raised when a project id would escape the projects root or is not filesystem-safe."""
