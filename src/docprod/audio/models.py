from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_VOICE_INSTRUCTIONS = (
    "Speak in natural Turkish as a calm serious documentary narrator. "
    "Measured pace, clear diction, restrained emotion, slightly suspenseful "
    "when appropriate, never theatrical, never like an advertisement. "
    "Maintain continuous storytelling flow and natural sentence rhythm."
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
