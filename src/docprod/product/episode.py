from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EpisodeBrief(BaseModel):
    """User-supplied episode data. Engine-owned fields stay empty until generation."""

    model_config = ConfigDict(extra="forbid")

    series_slug: str
    episode_number: int
    title: str = ""
    language: str = "tr"
    location: str = ""
    primary_tone: str = ""
    secondary_tone: str = ""
    target_duration_seconds: tuple[float, float] = (45.0, 60.0)
    cast_names: list[str] = Field(default_factory=list)
    premise: str = ""
    ending: str = ""
    premise_locked: bool = False
    engine_owns_structure: bool = True


class LocationBible(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    interior_layout: str = ""
    tables: str = ""
    counter: str = ""
    windows: str = ""
    entrance: str = ""
    exterior: str = ""
    lighting: str = ""
    time_of_day: str = ""
    props: list[str] = Field(default_factory=list)
    engine_owned_details: bool = True


class StoryCallSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    role: str
    model_id: str
    count: int = 1
    purpose: str
    estimated_input_tokens: int = 0
    reserved_input_tokens: int = 0
    estimated_output_tokens: int = 0
    reserved_output_tokens: int = 0
    expected_usd: float = 0.0
    reserved_usd: float = 0.0


class StoryGenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_slug: str
    episode_number: int
    quality_profile: str = "premium"
    flagship: bool = True
    treatment_count: int = 3
    calls: list[StoryCallSpec] = Field(default_factory=list)
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    reserved_input_tokens: int = 0
    reserved_output_tokens: int = 0
    estimated_usd: float | None = None
    reserved_usd: float = 0.0
    cost_confidence: str = "known"
    hard_cap_usd: float = 2.5
    cap_ok: bool = True
    execute: bool = False
    media_calls: int = 0
    send_image_binaries: bool = False
    notes: list[str] = Field(default_factory=list)


class ShotRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    scene_id: str = ""
    production_class: str = ""
    cast_refs: list[str] = Field(default_factory=list)
    action: str = ""
    framing: str = ""
    preferred_model: str = ""
    fallback_model: str = ""
    implementation_status: str = ""
    identity_required: bool = True


class EpisodeShotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shots: list[ShotRequirement] = Field(default_factory=list)
    engine_owned: bool = True


class VoiceAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_name: str
    provider: str
    voice_id: str
    display_name: str
    language: str = "tr"
    fallback_provider: str = "openai"
    fallback_voice_id: str = ""
    vibe: str = ""
    cloning: bool = False
