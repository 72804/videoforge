from __future__ import annotations

from enum import StrEnum

from docprod.quality.enums import ReferenceMode as EngineReferenceMode

# Re-export engine identity modes so product code does not fork them.
ReferenceMode = EngineReferenceMode


class ContentType(StrEnum):
    NARRATED = "narrated"
    DRAMATIC = "dramatic"
    HYBRID = "hybrid"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    QUOTED = "quoted"
    AWAITING_PAYMENT = "awaiting_payment"
    GENERATING = "generating"
    PARTIAL = "partial"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class DurationMode(StrEnum):
    AUTO = "AUTO"
    FIXED = "FIXED"


class AspectRatio(StrEnum):
    WIDESCREEN = "16:9"
    VERTICAL = "9:16"
    SQUARE = "1:1"


class StaleKind(StrEnum):
    FRESH = "fresh"
    STALE_IMAGE = "stale_image"
    STALE_VIDEO = "stale_video"
    STALE_RENDER = "stale_render"


class JobStatus(StrEnum):
    WAITING_FOR_PAYMENT = "WAITING_FOR_PAYMENT"
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    GENERATING_SCRIPT = "GENERATING_SCRIPT"
    GENERATING_IMAGES = "GENERATING_IMAGES"
    GENERATING_VIDEO = "GENERATING_VIDEO"
    GENERATING_AUDIO = "GENERATING_AUDIO"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    RECOVERING_REMOTE = "RECOVERING_REMOTE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AttemptStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    RECOVERING_REMOTE = "RECOVERING_REMOTE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class PlanItemType(StrEnum):
    SCRIPT = "script"
    STILL = "still"
    VIDEO = "video"
    TTS = "tts"
    MUSIC = "music"
    SFX = "sfx"
    ALIGNMENT = "alignment"
    RENDER = "render"


class QuoteStatus(StrEnum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    AUTHORIZED = "AUTHORIZED"
    CONSUMED = "CONSUMED"


class StarTxnType(StrEnum):
    PURCHASE = "PURCHASE"
    GENERATION_DEBIT = "GENERATION_DEBIT"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    PROMO_CREDIT = "PROMO_CREDIT"


class LedgerStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOID = "VOID"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    REFUND_FAILED = "REFUND_FAILED"


class PaymentIntentStatus(StrEnum):
    OPEN = "OPEN"
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BillingMechanism(StrEnum):
    PAY_PER_GENERATION = "PAY_PER_GENERATION"
    PREPAID_CREDITS = "PREPAID_CREDITS"


class ProviderOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    EMPTY_RESULT = "EMPTY_RESULT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ProviderBilledStatus(StrEnum):
    NOT_BILLED = "NOT_BILLED"
    BILLED = "BILLED"
    UNKNOWN = "UNKNOWN"


class CustomerBillingOutcome(StrEnum):
    NOT_CHARGED = "NOT_CHARGED"
    DEBITED = "DEBITED"
    REFUND_ELIGIBLE = "REFUND_ELIGIBLE"
    POLICY_PENDING = "POLICY_PENDING"


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    RENDER = "render"
    UPLOAD = "upload"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ModelCapability(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"
    MUSIC = "music"
    AUTO = "auto"
