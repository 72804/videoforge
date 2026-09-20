from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class HealthResponse(BaseModel):
    status: str = "ok"
    database: str | None = None
    worker: str | None = None


class ReadyResponse(BaseModel):
    status: str = "ok"
    database: str | None = None


class AuthRequest(BaseModel):
    init_data: str


class DevAuthRequest(BaseModel):
    telegram_user_id: int = 11
    first_name: str = "Dev"


class UserView(BaseModel):
    id: str
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    language_code: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: UserView


class ProjectCreate(BaseModel):
    prompt: str
    title: str | None = None
    duration_mode: str = "AUTO"
    target_duration_seconds: float | None = None
    aspect_ratio: str = "9:16"
    language: str = "en"
    quality_profile: str = "balanced"
    default_image_model: str = "auto"
    default_video_model: str = "auto"
    default_text_model: str = "auto"
    default_voice_model: str = "auto"
    style: str = ""


class ProjectPatch(BaseModel):
    title: str | None = None
    prompt: str | None = None
    duration_mode: str | None = None
    target_duration_seconds: float | None = None
    aspect_ratio: str | None = None
    language: str | None = None
    quality_profile: str | None = None
    default_image_model: str | None = None
    default_video_model: str | None = None
    default_text_model: str | None = None
    default_voice_model: str | None = None
    style: str | None = None


class ProjectSummaryView(BaseModel):
    id: str
    title: str
    status: str
    thumbnail_url: str | None = None
    duration_seconds: float | None = None
    scene_count: int
    progress: dict[str, int] | None = None
    updated_at: str
    prompt: str | None = None
    duration_mode: str | None = None
    target_duration_seconds: float | None = None
    aspect_ratio: str | None = None
    language: str | None = None
    quality_profile: str | None = None
    default_image_model: str | None = None
    default_video_model: str | None = None
    default_text_model: str | None = None
    default_voice_model: str | None = None
    style: str | None = None
    active_job_id: str | None = None
    active_job_status: str | None = None


class CharacterCreate(BaseModel):
    name: str
    description: str = ""
    locked_identity: bool = False


class CharacterPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    locked_identity: bool | None = None


class CharacterView(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    locked_identity: bool
    primary_reference_id: str | None = None


class CharacterReferenceView(BaseModel):
    id: str
    character_id: str
    sha256: str
    role: str
    primary: bool
    width: int
    height: int
    mime: str


class PlanRequest(BaseModel):
    kind: str = "full_project"
    scene_id: str | None = None


class PlanLineItem(BaseModel):
    type: str
    model: str
    quantity: float
    estimated_provider_usd: float
    customer_stars: int


class PlanView(BaseModel):
    plan_id: str
    plan_hash: str
    estimate_source: str = "server"
    scene_count: int
    duration_seconds: float
    image_generations: float
    video_generations: float
    tts: float
    music: float
    provider_cost_estimate: float
    customer_star_estimate: int
    line_items: list[PlanLineItem]


class QuoteRequest(BaseModel):
    plan_id: str


class QuoteView(BaseModel):
    quote_id: str
    plan_hash: str
    stars: int
    expires_at: str
    status: str
    simulated: bool = False


class GenerateRequest(BaseModel):
    quote_id: str
    kind: str = "full_project"
    scene_id: str | None = None


class JobAccepted(BaseModel):
    job_id: str
    status: str


class WorkUnitView(BaseModel):
    type: str
    completed: int
    total: int


class JobView(BaseModel):
    job_id: str
    project_id: str
    status: str
    work_units: list[WorkUnitView]
    current_stage: str
    failure_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class SceneSummaryView(BaseModel):
    id: str
    order_index: int
    thumbnail_url: str | None = None
    duration_seconds: float
    characters: list[str]
    status: str
    production_class: str
    image_model: str
    video_model: str
    locked: bool
    version_number: int
    estimated_regeneration_stars: int
    image_asset_version_id: str | None = None
    video_asset_version_id: str | None = None
    visual_prompt: str = ""
    motion_prompt: str = ""


class ScenePatch(BaseModel):
    visual_prompt: str | None = None
    motion_prompt: str | None = None
    duration_seconds: float | None = None
    character_ids: list[str] | None = None
    image_model: str | None = None
    video_model: str | None = None


class ReorderRequest(BaseModel):
    scene_ids: list[str]


class ModelView(BaseModel):
    id: str
    display_name: str
    capabilities: list[str]
    quality_tier: str
    available: bool


class UsageTxnView(BaseModel):
    id: str
    type: str
    stars: int
    simulated: bool
    created_at: str
    project_id: str | None = None


class UsageView(BaseModel):
    transactions: list[UsageTxnView]
    stars_debited: int
    stars_purchased: int
