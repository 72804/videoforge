from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SoundNeedType = Literal["music", "ambience", "event_sfx", "transition_sting", "silence"]
SoundCategory = Literal[
    "MUSIC_BED",
    "AMBIENCE",
    "EVENT_SFX",
    "TRANSITION_STING",
    "GENERATED_SYNC_AUDIO",
]
Importance = Literal["low", "medium", "high"]
ReuseClass = Literal["episode_specific", "channel_reusable", "generic_reusable"]


class TensionKnot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: float
    chapter: str
    story_state: str
    tension: float
    mystery: float
    urgency: float
    reflection: float
    information_density: float
    music_need: float
    silence_preference: float
    reason: str


class SoundNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sound_need_id: str
    start: float
    end: float
    scene_ids: list[str] = Field(default_factory=list)
    chapter: str = ""
    type: SoundNeedType
    story_reason: str
    importance: Importance = "medium"
    mood: str = ""
    tension: float = 0.4
    energy: float = 0.4
    desired_texture: str = ""
    desired_duration: float = 0.0
    sync_required: bool = False
    reuse_allowed: bool = True
    generation_allowed: bool = True
    notes: str = ""


class MusicSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    music_section_id: str
    start: float
    end: float
    chapter_ids: list[str] = Field(default_factory=list)
    purpose: str
    mood: str
    tension_start: float = 0.3
    tension_peak: float = 0.5
    tension_end: float = 0.3
    energy_start: float = 0.3
    energy_end: float = 0.3
    bpm_range: str = "60-84"
    density: str = "low"
    brightness: str = "dark"
    tonal_direction: str = "restrained documentary underscore"
    instrumentation: str = "muted pulse, textural strings, no vocals"
    avoid: str = "lyrics, vocals, trailer booms, giant climaxes"
    transition_in: str = "fade"
    transition_out: str = "crossfade"
    visual_context_scene_ids: list[str] = Field(default_factory=list)
    visual_context_frames: list[str] = Field(default_factory=list)
    reuse_allowed: bool = True
    library_asset_id: str = ""
    generation_required: bool = False
    generation_prompt: str = ""
    provider: str = "google"
    model: str = "lyria-3.5"
    status: str = "planned"


class SonicProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "documentary_investigative_v1"
    genre: str = "documentary / investigative"
    tone: str = "restrained, serious"
    narration_priority: bool = True
    vocals: bool = False
    trailer_climaxes: bool = False
    percussion: str = "muted"
    low_pulse: bool = True
    texture: str = "subtle strings/synth"
    speech_headroom: bool = True
    reveal_stings: str = "occasional restrained"
    resolution_palette: str = "reflective legal"
    opening_motif: str = ""
    investigation_motif: str = ""
    reveal_motif: str = ""
    resolution_motif: str = ""


class SoundAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    category: SoundCategory
    source_type: str
    provider: str = "local"
    model: str = ""
    prompt: str = ""
    duration: float = 0.0
    sample_rate: int = 48000
    channels: int = 2
    tags: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)
    intensity: float = 0.4
    texture: str = ""
    story_roles: list[str] = Field(default_factory=list)
    reuse_allowed: bool = True
    license_note: str = "generated/generic; not archival event audio"
    generated_provenance: str = ""
    sha256: str = ""
    embedding_id: str = ""
    usage_count: int = 0
    last_used_project: str = ""
    local_path: str = ""
    reuse_class: ReuseClass = "episode_specific"
    notes: str = ""


class SoundCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cue_id: str
    sound_need_id: str
    type: SoundNeedType
    start: float
    end: float
    scene_ids: list[str] = Field(default_factory=list)
    asset_id: str = ""
    source_type: str = ""
    generated_or_reused: str = "reused"
    sync_required: bool = False
    gain_db: float = -18.0
    fade_in: float = 0.4
    fade_out: float = 0.6
    duck_under_voice: bool = True
    sidechain_amount: float = 0.7
    story_reason: str = ""
    license_or_generation_metadata: str = "generated/generic"
    status: str = "planned"


class TimeSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float
    end: float
    reason: str = ""


class SoundPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    duration: float
    sonic_profile: SonicProfile
    knots: list[TensionKnot] = Field(default_factory=list)
    needs: list[SoundNeed] = Field(default_factory=list)
    music_sections: list[MusicSection] = Field(default_factory=list)
    cues: list[SoundCue] = Field(default_factory=list)
    silence_spans: list[TimeSpan] = Field(default_factory=list)
    reused_asset_ids: list[str] = Field(default_factory=list)
    generation_required_music: int = 0
    notes: list[str] = Field(default_factory=list)
    paid_api_calls: dict[str, int] = Field(default_factory=dict)
