from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


PK = String(36)


class TelegramUserRow(Base):
    __tablename__ = "telegram_users"

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("projects_user_updated_idx", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    duration_mode: Mapped[str] = mapped_column(Text, nullable=False)
    target_duration_seconds: Mapped[float | None] = mapped_column(Float)
    aspect_ratio: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    quality_profile: Mapped[str] = mapped_column(Text, nullable=False)
    default_image_model: Mapped[str] = mapped_column(Text, nullable=False)
    default_video_model: Mapped[str] = mapped_column(Text, nullable=False)
    default_text_model: Mapped[str] = mapped_column(Text, nullable=False)
    default_voice_model: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active_script_version_id: Mapped[str | None] = mapped_column(PK)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CharacterRow(Base):
    __tablename__ = "characters"
    __table_args__ = (Index("characters_project_id_idx", "project_id"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    locked_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    primary_reference_id: Mapped[str | None] = mapped_column(PK)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CharacterReferenceRow(Base):
    __tablename__ = "character_references"

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    primary_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="primary")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScriptVersionRow(Base):
    __tablename__ = "script_versions"
    __table_args__ = (UniqueConstraint("id", name="script_versions_id_key"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneRow(Base):
    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint("project_id", "order_index", name="scenes_project_order_key"),
        Index("scenes_project_order_idx", "project_id", "order_index"),
    )

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    active_version_id: Mapped[str | None] = mapped_column(PK)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneVersionRow(Base):
    __tablename__ = "scene_versions"
    __table_args__ = (Index("scene_versions_scene_id_idx", "scene_id"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    visual_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    motion_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    character_ids: Mapped[Any] = mapped_column(JSONB, nullable=False)
    dialogue: Mapped[str] = mapped_column(Text, nullable=False, default="")
    narration: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    production_class: Mapped[str] = mapped_column(Text, nullable=False)
    image_model: Mapped[str] = mapped_column(Text, nullable=False)
    video_model: Mapped[str] = mapped_column(Text, nullable=False)
    image_asset_version_id: Mapped[str | None] = mapped_column(PK)
    video_asset_version_id: Mapped[str | None] = mapped_column(PK)
    image_stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    video_stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetRow(Base):
    __tablename__ = "assets"
    __table_args__ = (Index("assets_project_id_idx", "project_id"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    scene_id: Mapped[str | None] = mapped_column(PK)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetVersionRow(Base):
    __tablename__ = "asset_versions"
    __table_args__ = (Index("asset_versions_asset_id_idx", "asset_id"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mime: Mapped[str] = mapped_column(Text, nullable=False, default="")
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GenerationPlanRow(Base):
    __tablename__ = "generation_plans"

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    plan_hash: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_provider_usd: Mapped[float] = mapped_column(Float, nullable=False)
    customer_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    items: Mapped[Any] = mapped_column(JSONB, nullable=False)
    scoped_scene_ids: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GenerationPlanItemRow(Base):
    __tablename__ = "generation_plan_items"

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("generation_plans.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_provider_usd: Mapped[float] = mapped_column(Float, nullable=False)
    customer_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    dependencies: Mapped[Any] = mapped_column(JSONB, nullable=False)
    scene_id: Mapped[str | None] = mapped_column(PK)


class StarQuoteRow(Base):
    __tablename__ = "star_quotes"

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    generation_plan_id: Mapped[str] = mapped_column(
        ForeignKey("generation_plans.id"), nullable=False
    )
    generation_plan_hash: Mapped[str] = mapped_column(Text, nullable=False)
    quote_hash: Mapped[str] = mapped_column(Text, nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_provider_usd: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)


class GenerationJobRow(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index("generation_jobs_status_created_idx", "status", "created_at"),
        Index("generation_jobs_user_project_idx", "user_id", "project_id"),
        Index("generation_jobs_user_status_idx", "user_id", "status"),
        UniqueConstraint("payment_id", name="generation_jobs_payment_id_key"),
    )

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("star_quotes.id"))
    plan_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    authorized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payment_id: Mapped[str | None] = mapped_column(PK)
    progress: Mapped[Any] = mapped_column(JSONB, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="full_project")
    target_scene_id: Mapped[str | None] = mapped_column(PK)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_provider_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provider_cost_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reserved_provider_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GenerationAttemptRow(Base):
    __tablename__ = "generation_attempts"
    __table_args__ = (Index("generation_attempts_job_status_idx", "job_id", "status"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("generation_jobs.id"), nullable=False)
    scene_id: Mapped[str | None] = mapped_column(PK)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    provider_billed: Mapped[str] = mapped_column(Text, nullable=False)
    customer_billing: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remote_operation_id: Mapped[str | None] = mapped_column(Text)
    estimated_provider_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_provider_cost: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RenderRow(Base):
    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StarTransactionRow(Base):
    __tablename__ = "star_transactions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="star_transactions_idem_key"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(PK)
    generation_job_id: Mapped[str | None] = mapped_column(PK)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_payment_id: Mapped[str | None] = mapped_column(Text)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramPaymentRow(Base):
    __tablename__ = "telegram_payments"
    __table_args__ = (
        UniqueConstraint("telegram_payment_id", name="telegram_payments_tg_id_key"),
        Index("telegram_payments_tg_id_idx", "telegram_payment_id"),
    )

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    quote_id: Mapped[str] = mapped_column(ForeignKey("star_quotes.id"), nullable=False)
    telegram_payment_id: Mapped[str] = mapped_column(Text, nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_payload: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refund_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaymentIntentRow(Base):
    __tablename__ = "payment_intents"
    __table_args__ = (Index("payment_intents_quote_idx", "quote_id"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    quote_id: Mapped[str] = mapped_column(ForeignKey("star_quotes.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    plan_hash: Mapped[str] = mapped_column(Text, nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationOutboxRow(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (Index("notification_outbox_status_next_idx", "status", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(PK)
    job_id: Mapped[str | None] = mapped_column(PK)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "action", "idempotency_key", name="idempotency_user_action_key"
        ),
        Index("idempotency_user_action_key_idx", "user_id", "action", "idempotency_key"),
    )

    id: Mapped[str] = mapped_column(PK, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("telegram_users.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    result_type: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[str | None] = mapped_column(PK)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkerHeartbeatRow(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(Text, primary_key=True)
    hostname: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_job_id: Mapped[str | None] = mapped_column(PK)
