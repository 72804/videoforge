from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docprod.models.project import SCHEMA_VERSION

TIMING_TOLERANCE = 1e-4


class WordTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str
    start: float
    end: float

    @model_validator(mode="after")
    def _validate_span(self) -> WordTiming:
        if not self.word.strip():
            raise ValueError("word must not be empty")
        if self.start < 0:
            raise ValueError("word start must be >= 0")
        if self.end <= self.start:
            raise ValueError("word end must be > start")
        return self


class Utterance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    start: float
    end: float
    words: list[WordTiming] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_span_and_words(self) -> Utterance:
        if not self.id.strip():
            raise ValueError("utterance id must not be empty")
        if not self.text.strip():
            raise ValueError("utterance text must not be empty")
        if self.start < 0:
            raise ValueError("utterance start must be >= 0")
        if self.end <= self.start:
            raise ValueError("utterance end must be > start")
        previous_end: float | None = None
        for word in self.words:
            if word.start < self.start - TIMING_TOLERANCE:
                raise ValueError(f"word {word.word!r} starts before utterance")
            if word.end > self.end + TIMING_TOLERANCE:
                raise ValueError(f"word {word.word!r} ends after utterance")
            if previous_end is not None and word.start < previous_end - TIMING_TOLERANCE:
                raise ValueError("word timings must not overlap")
            previous_end = word.end
        return self


class NarrationScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    language: str
    full_text: str
    utterances: list[Utterance] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_utterances(self) -> NarrationScript:
        if not self.language.strip():
            raise ValueError("language must not be empty")
        previous_end: float | None = None
        previous_start: float | None = None
        seen_ids: set[str] = set()
        for utterance in self.utterances:
            if utterance.id in seen_ids:
                raise ValueError(f"duplicate utterance id: {utterance.id}")
            seen_ids.add(utterance.id)
            if previous_start is not None and utterance.start < previous_start:
                raise ValueError("utterances must be ordered by start time")
            if previous_end is not None and utterance.start < previous_end - TIMING_TOLERANCE:
                raise ValueError("utterances must not overlap")
            previous_start = utterance.start
            previous_end = utterance.end
        return self
