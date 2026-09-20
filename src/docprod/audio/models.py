from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_VOICE_INSTRUCTIONS = (
    "Speak in natural Turkish as a calm serious documentary narrator. "
    "Measured pace, clear diction, restrained emotion, slightly suspenseful "
    "when appropriate, never theatrical, never like an advertisement. "
    "Maintain continuous storytelling flow and natural sentence rhythm."
)

DRAMA_VOICE_INSTRUCTIONS = (
    "Speak in natural Turkish as a controlled dramatic storyteller. "
    "Slightly dry and deadpan. Deliver an absurd neighborhood story seriously. "
    "Measured pace, clear diction, not cartoonish, not overly emotional, "
    "not a commercial advertisement. Humor comes from the writing and timing, "
    "not from exaggerated acting. Maintain continuous storytelling flow."
)

TTS_CONTINUATION_INSTRUCTIONS = (
    "This is a continuation of the same documentary narration. Maintain the same "
    "voice character, pacing, energy, seriousness, and delivery as the preceding "
    "section. Begin naturally, without sounding like a new introduction."
)

TTS_ONCE_INSTRUCTIONS = (
    "Read the supplied narration exactly once from beginning to end. "
    "Do not restart, repeat, summarize, or add any words."
)

ALIGNMENT_MATCH_THRESHOLD = 0.95
SCENE_END_TAIL = 0.30


class SceneNarrationSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    narration: str
    char_start: int
    char_end: int
    planned_duration: float


class CanonicalNarrationScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    text: str
    spans: list[SceneNarrationSpan] = Field(default_factory=list)


class WhisperWord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str
    start: float
    end: float


class AlignedToken(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    scene_id: str
    start: float | None = None
    end: float | None = None
    whisper_match: str | None = None
    status: str = "unmatched"
    interpolated: bool = False
    timing_source: str | None = None


class AlignmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    language: str | None = None
    canonical_word_count: int
    matched_word_count: int
    interpolated_word_count: int
    unmatched_word_count: int
    trailing_unmatched_count: int = 0
    leading_unmatched_count: int = 0
    match_fraction: float
    tokens: list[AlignedToken] = Field(default_factory=list)
    quality_passed: bool = False


class NarrationMasterMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    provider: str
    model: str
    voice: str
    speed: float
    instructions: str
    script_hash: str
    request_hash: str
    duration: float
    sample_rate: int
    channels: int
    output_sha256: str
    usage: dict[str, Any] | None = None
    loudness: dict[str, str] | None = None
    generation_status: str = "success"
    tts_request_count: int = 1
    whisper_request_count: int = 0
    chunk_count: int = 1
    chunk_durations: list[float] = Field(default_factory=list)
    join_silences: list[float] = Field(default_factory=list)
    loudness_input: dict[str, str] | None = None


class NarrationChunkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    word_start: int
    word_end: int
    chapter_start: str = ""
    chapter_end: str = ""
    character_count: int
    estimated_token_count: int
    script_hash: str
    boundary_type: str = "end"
    instructions: str = ""
    boundary_reason: str = ""


class NarrationChunkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    canonical_character_count: int
    canonical_word_count: int
    chunk_count: int
    canonical_script_hash: str
    chunks: list[NarrationChunkSpec] = Field(default_factory=list)


class ChunkAudioWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word_start: int
    word_end: int
    audio_start: float
    audio_end: float


class RuntimeSceneTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    start: float
    end: float
    duration: float
    planned_duration: float
    narration: str
    asset_unit_id: str = ""
    source_asset: str = ""
    runtime_strategy: str = ""


class RuntimeTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    audio_duration: float
    total_duration: float
    scenes: list[RuntimeSceneTiming] = Field(default_factory=list)
