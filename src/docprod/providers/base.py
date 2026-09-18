from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class TextGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    model: str
    provider: str
    prompt_hash: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class TTSResult(BaseModel):
    """Metadata-only TTS result. No audio bytes in Phase 1."""

    model_config = ConfigDict(extra="forbid")

    text: str
    duration_seconds: float
    sample_rate: int
    audio_format: str
    provider: str
    model: str
    note: str
    metadata: dict[str, str] = Field(default_factory=dict)


class ImageGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    width: int
    height: int
    provider: str
    model: str
    would_write: str
    note: str
    seed: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class VideoGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    duration_seconds: float
    provider: str
    model: str
    would_write: str
    note: str
    seed: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class TextGenerationProvider(Protocol):
    def generate_text(self, prompt: str, *, seed: int | None = None) -> TextGenerationResult: ...


class TTSProvider(Protocol):
    def synthesize(self, text: str, *, seed: int | None = None) -> TTSResult: ...


class ImageGenerationProvider(Protocol):
    def generate_image(
        self,
        prompt: str,
        *,
        seed: int | None = None,
        width: int = 1920,
        height: int = 1080,
    ) -> ImageGenerationResult: ...


class VideoGenerationProvider(Protocol):
    def generate_video(
        self,
        prompt: str,
        *,
        seed: int | None = None,
        duration_seconds: float = 4.0,
    ) -> VideoGenerationResult: ...
