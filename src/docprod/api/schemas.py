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
    payment_mode: str | None = None
    generation_mode: str | None = None
    allow_paid_generation: bool | None = None


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
    display_name: str = ""
    bio: str = ""
    default_traits: list[str] = Field(default_factory=list)
    allow_friends_to_cast_me: bool = False


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
    content_type: str = "custom_story"
    visibility: str = "PRIVATE"


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
    visibility: str | None = None


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
    content_type: str | None = None
    visibility: str | None = None
    series_id: str | None = None
    episode_number: int | None = None
    active_job_id: str | None = None
    active_job_status: str | None = None
    final_asset_version_id: str | None = None


class CharacterCreate(BaseModel):
    name: str
    description: str = ""
    locked_identity: bool = False
    personality_traits: list[str] = Field(default_factory=list)
    role_archetype: str = ""
    appearance_notes: str = ""
    catchphrases: list[str] = Field(default_factory=list)
    behavioral_quirks: list[str] = Field(default_factory=list)


class CharacterPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    locked_identity: bool | None = None
    personality_traits: list[str] | None = None
    role_archetype: str | None = None
    appearance_notes: str | None = None


class CharacterView(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    locked_identity: bool
    primary_reference_id: str | None = None
    display_name: str = ""
    personality_traits: list[str] = Field(default_factory=list)
    role_archetype: str = ""
    kind: str = "standalone"
    linked_user_id: str | None = None
    voice_profile_id: str | None = None


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


class ProfilePatch(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    default_traits: list[str] | None = None
    allow_friends_to_cast_me: bool | None = None


class FriendRequestBody(BaseModel):
    username: str | None = None
    user_id: str | None = None


class FriendshipView(BaseModel):
    id: str
    requester_id: str
    addressee_id: str
    status: str


class PersonaCreate(BaseModel):
    name: str
    description: str = ""
    personality_traits: list[str] = Field(default_factory=list)
    role_archetype: str = ""
    appearance_notes: str = ""
    catchphrases: list[str] = Field(default_factory=list)
    behavioral_quirks: list[str] = Field(default_factory=list)


class PersonaView(BaseModel):
    id: str
    owner_user_id: str
    name: str
    display_name: str
    description: str
    personality_traits: list[str]
    role_archetype: str
    kind: str
    linked_user_id: str | None = None
    locked_identity: bool
    external_ref_path: str = ""


class CastBody(BaseModel):
    persona_id: str | None = None
    friend_user_id: str | None = None


class SeriesView(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    episode_id: str | None = None


class VoiceProfileView(BaseModel):
    id: str
    provider: str
    voice_id: str
    display_name: str
    language: str
