from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docprod.research.models import ApiUsage

WRITER_PROMPT_VERSION = "1.0"
TARGET_WORD_MIN = 850
TARGET_WORD_MAX = 1050
WORD_GATE_MIN = 700
WORD_GATE_MAX = 1300
WORDS_PER_MINUTE = 145.0


class StoryChapter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter_id: str
    title: str
    purpose: str
    beat_ids: list[str] = Field(default_factory=list)


class StoryOutline(BaseModel):
    model_config = ConfigDict(extra="ignore")

    logline: str = ""
    chapters: list[StoryChapter] = Field(default_factory=list)


class NarrationBeat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    beat_id: str
    narration: str
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    chapter: str = "body"
    purpose: str = "narration"


class ScriptValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    word_count: int
    estimated_runtime_minutes: float
    beat_count: int
    chapter_count: int
    claims_referenced: int
    sources_referenced: int
    unsupported_beat_count: int
    unsupported_beat_ids: list[str] = Field(default_factory=list)
    within_target_word_range: bool
    failures: list[str] = Field(default_factory=list)
    repetition_notes: list[str] = Field(default_factory=list)


class NarrationScript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    project_id: str
    language: str = "tr"
    outline: StoryOutline
    beats: list[NarrationBeat] = Field(default_factory=list)
    full_narration: str = ""
    word_count: int = 0
    estimated_runtime_minutes: float = 0.0
    writer_model: str = ""
    request_hash: str = ""
    usage: ApiUsage | None = None
    cache_hit: bool = False
    validation: ScriptValidationSummary | None = None
