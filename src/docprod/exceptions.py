class PaidApiDisabledError(RuntimeError):
    """Raised when a paid provider is requested while ALLOW_PAID_APIS is false."""


class PaidApiNotConfirmedError(RuntimeError):
    """Raised when a paid call is attempted without an explicit --confirm-paid flag."""


class MissingApiKeyError(RuntimeError):
    """Raised when a required provider API key is not configured."""


class StockProviderError(RuntimeError):
    """Raised when a stock provider request fails without leaking secrets."""


class ArchiveProviderError(RuntimeError):
    """Raised when an archive/Commons request fails without leaking secrets."""


class ZeroPlaceholderError(RuntimeError):
    """Raised when a scene still resolves to a debug placeholder visual."""


class MaxPaidRequestsExceededError(RuntimeError):
    """Raised when a batch would exceed the explicit paid-request cap."""


class TtsInputLimitError(RuntimeError):
    """Raised when narration exceeds the TTS model's input limit."""


class AlignmentQualityError(RuntimeError):
    """Raised when Whisper-to-script alignment is too weak to retime the film."""


class IntegrityBlockedError(RuntimeError):
    """Raised when TTS/master integrity fails before paid alignment or promotion."""


class UnsafeProjectIdError(ValueError):
    """Raised when a project id would escape the projects root or is not filesystem-safe."""


class ResearchQualityError(RuntimeError):
    """Raised when web research does not meet the evidence quality gate."""


class DossierValidationError(RuntimeError):
    """Raised when the structured dossier is not fully sourced or internally consistent."""


class ScriptValidationError(RuntimeError):
    """Raised when the narration script invents unsupported detail or fails length checks."""


class SemanticPlannerError(RuntimeError):
    """Raised when semantic scene planning fails (parse, budget, or validation)."""


class UnimplementedProviderError(RuntimeError):
    """Raised when a catalogued provider has no implemented network adapter."""


class ProviderOfflineError(RuntimeError):
    """Raised when a local inference endpoint is configured but not reachable."""
