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
    spatial_layout: dict[str, str] = Field(default_factory=dict)
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
    visible_cast: list[str] = Field(default_factory=list)
    speaking_cast: list[str] = Field(default_factory=list)
    offscreen_speakers: list[str] = Field(default_factory=list)
    action: str = ""
    framing: str = ""
    coverage: str = ""
    duration_seconds: float = 0.0
    props: list[str] = Field(default_factory=list)
    prop_notes: str = ""
    overlay_kind: str = ""
    overlay_copy: list[str] = Field(default_factory=list)
    preferred_model: str = ""
    fallback_model: str = ""
    implementation_status: str = ""
    ideal_model: str = ""
    ideal_status: str = ""
    executable_model: str = ""
    fallback_chain: list[str] = Field(default_factory=list)
    plate_model: str = ""
    estimated_usd: float | None = None
    voice_required: bool = False
    sfx_required: bool = False
    music_required: bool = False
    motion_graphics_required: bool = False
    location_slot: str = ""
    locked_refs: list[str] = Field(default_factory=list)
    identity_required: bool = True


class EpisodeShotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shots: list[ShotRequirement] = Field(default_factory=list)
    engine_owned: bool = True
    total_duration_seconds: float = 0.0
    spatial_layout: dict[str, str] = Field(default_factory=dict)
    role_coverage: dict[str, str] = Field(default_factory=dict)
    revisions: list[str] = Field(default_factory=list)


class ShotProductionLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    duration_seconds: float
    production_class: str
    visible_characters: list[str] = Field(default_factory=list)
    locked_refs: list[str] = Field(default_factory=list)
    ideal_model: str = ""
    ideal_status: str = ""
    executable_model: str = ""
    fallback_chain: list[str] = Field(default_factory=list)
    estimated_media_usd: float | None = None
    voice_required: bool = False
    sfx_required: bool = False
    music_required: bool = False
    motion_graphics_required: bool = False
    coverage: str = ""
    props: list[str] = Field(default_factory=list)


class EpisodeProductionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_profile: str
    shots: list[ShotProductionLine] = Field(default_factory=list)
    image_usd: float = 0.0
    video_usd: float = 0.0
    voice_usd: float = 0.0
    audio_usd: float = 0.0
    expected_usd: float = 0.0
    reserved_usd: float = 0.0
    notes: list[str] = Field(default_factory=list)


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
