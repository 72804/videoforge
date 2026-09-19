from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class MusicGenerateRequest:
    prompt: str
    duration_hint_seconds: float
    image_paths: list[Path]
    wav: bool = True


@dataclass
class MusicGenerateResult:
    audio_bytes: bytes
    provider: str
    model: str
    mime: str
    prompt: str
    synthid: str | None = None
    metadata: dict[str, str] | None = None


class MusicGenerationProvider(Protocol):
    name: str
    model: str

    def generate_music(
        self, request: MusicGenerateRequest, *, confirm_paid: bool, use_cache: bool = True
    ) -> MusicGenerateResult: ...


class AdaptiveMusicProvider(Protocol):
    """Future Lyria RealTime backend. Disabled by default in production."""

    name: str
    model: str
    enabled: bool

    def is_available(self) -> bool: ...
