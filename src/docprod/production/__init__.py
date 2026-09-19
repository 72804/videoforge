from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from docprod.models.enums import AssetStrategy

AssetStatus = Literal[
    "READY_LOCAL",
    "READY_STOCK",
    "READY_ARCHIVE",
    "NEEDS_AI_IMAGE",
    "NEEDS_AI_VIDEO",
    "READY_AI_IMAGE",
    "READY_AI_KEYFRAME",
    "REVIEW_REQUIRED",
    "UNRESOLVED",
]
ReuseMode = Literal["unique", "shared_trim", "shared_continue"]
TrimPolicy = Literal["per_scene_window", "continuous"]


class PhotoSequenceAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stills: list[str] = Field(default_factory=list)
    concept_keys: list[str] = Field(default_factory=list)


class AssetUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_unit_id: str
    scene_ids: list[str]
    source_strategy: AssetStrategy
    continuous_duration: float
    visual_concept: str
    generation_required: bool = False
    provider: str = ""
    reuse_mode: ReuseMode = "unique"
    trim_policy: TrimPolicy = "per_scene_window"
    continuity_group: str = ""
    estimated_cost: str = "unresolved"
    status: AssetStatus = "UNRESOLVED"
    source: str = ""
    source_path: str = ""
    credit_id: str = ""
    generation_spec_path: str = ""
    warnings: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class AIStillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_unit_id: str
    scene_ids: list[str]
    duration_needed: float
    prompt: str
    negative_constraints: list[str] = Field(default_factory=list)
    historical_constraints: list[str] = Field(default_factory=list)
    continuity_refs: list[str] = Field(default_factory=list)
    aspect_ratio: str = "16:9"
    quality: str = "medium"
    estimated_requests: int = 1


class AIVideoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_unit_id: str
    scene_ids: list[str]
    duration_needed: float
    start_image_requirement: str = "generate_or_use_still"
    motion_description: str
    historical_constraints: list[str] = Field(default_factory=list)
    estimated_requests: int = 1
    provider_neutral: bool = True


class ProductionCostPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    scene_count: int
    asset_unit_count: int
    saved_generation_count: int
    ai_still_scenes: int
    ai_still_units: int
    ai_video_scenes: int
    ai_video_units: int
    ai_video_seconds: float
    narration_minutes: float
    pexels_assets: int
    commons_assets: int
    local_assets: int
    research_model_requests_already_made: str = "see prior stages; dollar cost unresolved"
    known_image_cost: str = "price unresolved"
    known_video_cost: str = "price unresolved"
    known_tts_cost: str = "price unresolved"
    known_whisper_cost: str = "price unresolved"
    known_total: str = "price unresolved"
    notes: list[str] = Field(default_factory=list)


class AssetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    scene_count: int
    asset_unit_count: int
    saved_generation_count: int
    units: list[AssetUnit] = Field(default_factory=list)
    cost: ProductionCostPreview | None = None
