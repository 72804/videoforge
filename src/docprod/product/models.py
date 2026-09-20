from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from docprod.product.enums import (
    AspectRatio,
    AssetKind,
    AttemptStatus,
    ContentType,
    CustomerBillingOutcome,
    DurationMode,
    JobStatus,
    LedgerStatus,
    OutboxStatus,
    PaymentIntentStatus,
    PaymentStatus,
    PlanItemType,
    ProjectStatus,
    ProviderBilledStatus,
    ProviderOutcome,
    QuoteStatus,
    ReferenceMode,
    StaleKind,
    StarTxnType,
)
from docprod.product.ids import new_id


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    language_code: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("telegram_user_id")
    @classmethod
    def _positive_tg_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("telegram_user_id must be a positive integer")
        return value


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    title: str
    prompt: str
    content_type: ContentType = ContentType.DRAMATIC
    status: ProjectStatus = ProjectStatus.DRAFT
    duration_mode: DurationMode = DurationMode.AUTO
    target_duration_seconds: float | None = None
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    language: str = "en"
    quality_profile: str = "balanced"
    default_image_model: str = "auto"
    default_video_model: str = "auto"
    default_text_model: str = "auto"
    default_voice_model: str = "auto"
    style: str = ""
    active_script_version_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    archived_at: datetime | None = None

    @model_validator(mode="after")
    def _duration_rules(self) -> Project:
        if self.duration_mode is DurationMode.AUTO:
            if self.target_duration_seconds is not None:
                raise ValueError("AUTO duration must not set target_duration_seconds")
        elif self.target_duration_seconds is None or self.target_duration_seconds <= 0:
            raise ValueError("FIXED duration requires target_duration_seconds > 0")
        if not self.title.strip() or not self.prompt.strip():
            raise ValueError("title and prompt are required")
        return self


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    name: str
    description: str = ""
    locked_identity: bool = False
    primary_reference_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CharacterReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    character_id: str
    project_id: str
    storage_key: str
    sha256: str
    mode: ReferenceMode = ReferenceMode.CUSTOM
    primary: bool = False
    role: str = "primary"
    width: int = 0
    height: int = 0
    mime: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ScriptVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    body: str
    language: str
    created_at: datetime = Field(default_factory=utcnow)


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    order_index: int
    active_version_id: str | None = None
    locked: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class SceneVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    scene_id: str
    project_id: str
    visual_prompt: str
    motion_prompt: str = ""
    character_ids: list[str] = Field(default_factory=list)
    dialogue: str = ""
    narration: str = ""
    duration_seconds: float
    production_class: str = "simple_motion"
    image_model: str = "auto"
    video_model: str = "auto"
    image_asset_version_id: str | None = None
    video_asset_version_id: str | None = None
    image_stale: bool = True
    video_stale: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    scene_id: str | None = None
    kind: AssetKind
    created_at: datetime = Field(default_factory=utcnow)


class AssetVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    asset_id: str
    storage_key: str
    sha256: str
    model: str = ""
    provider: str = ""
    mime: str = ""
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    created_at: datetime = Field(default_factory=utcnow)


class GenerationPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: PlanItemType
    model: str
    quantity: float
    estimated_provider_usd: float
    customer_stars: int
    dependencies: list[str] = Field(default_factory=list)
    scene_id: str | None = None


class GenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    items: list[GenerationPlanItem]
    plan_hash: str
    estimated_provider_usd: float
    customer_stars: int
    scoped_scene_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class StarQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    user_id: str
    generation_plan_id: str
    generation_plan_hash: str
    quote_hash: str
    stars: int
    estimated_provider_usd: float
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    status: QuoteStatus = QuoteStatus.OPEN


class GenerationJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    user_id: str
    quote_id: str | None = None
    plan_hash: str
    status: JobStatus = JobStatus.WAITING_FOR_PAYMENT
    authorized: bool = False
    payment_id: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    kind: str = "full_project"
    target_scene_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_message: str | None = None
    error_code: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt_count: int = 0
    estimated_provider_cost: float = 0.0
    provider_cost_cap: float = 0.0
    reserved_provider_cost: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class GenerationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    job_id: str
    scene_id: str | None = None
    item_type: PlanItemType
    provider: str
    model: str
    provider_outcome: ProviderOutcome = ProviderOutcome.SKIPPED
    provider_billed: ProviderBilledStatus = ProviderBilledStatus.NOT_BILLED
    customer_billing: CustomerBillingOutcome = CustomerBillingOutcome.NOT_CHARGED
    error_code: str | None = None
    status: AttemptStatus = AttemptStatus.PENDING
    request_hash: str = ""
    remote_operation_id: str | None = None
    estimated_provider_cost: float = 0.0
    actual_provider_cost: float | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    safe_error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Render(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    storage_key: str
    stale: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class StarTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    project_id: str | None = None
    generation_job_id: str | None = None
    type: StarTxnType
    telegram_payment_id: str | None = None
    stars: int
    idempotency_key: str
    status: LedgerStatus = LedgerStatus.POSTED
    created_at: datetime = Field(default_factory=utcnow)


class TelegramPayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    quote_id: str
    telegram_payment_id: str
    stars: int
    status: PaymentStatus = PaymentStatus.CREATED
    invoice_payload: str = ""
    refund_status: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class PaymentIntent(BaseModel):
    """Opaque Stars invoice mapping. Telegram payload is this id only."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    quote_id: str
    project_id: str
    plan_hash: str
    stars: int
    invoice_url: str = ""
    status: PaymentIntentStatus = PaymentIntentStatus.OPEN
    telegram_payment_charge_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class NotificationOutbox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    project_id: str | None = None
    job_id: str | None = None
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    next_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class WorkUnits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    completed: int = 0
    total: int = 0

    @property
    def done(self) -> bool:
        return self.total > 0 and self.completed >= self.total


def stale_kind(version: SceneVersion, render_stale: bool) -> StaleKind:
    if version.image_stale:
        return StaleKind.STALE_IMAGE
    if version.video_stale:
        return StaleKind.STALE_VIDEO
    if render_stale:
        return StaleKind.STALE_RENDER
    return StaleKind.FRESH


class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    key: str
    user_id: str
    action: str
    request_hash: str
    status_code: int
    body: dict[str, Any] = Field(default_factory=dict)
    result_type: str | None = None
    result_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class WorkerHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str
    hostname: str = ""
    last_seen_at: datetime = Field(default_factory=utcnow)
    current_job_id: str | None = None
