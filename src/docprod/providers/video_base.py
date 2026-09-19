from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class VideoShotRequest:
    prompt: str
    negative_prompt: str
    image_path: Path
    duration_seconds: int = 8
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    count: int = 1
    native_audio_prompt: str = ""
    asset_unit_id: str = ""


@dataclass
class VideoShotResult:
    video_bytes: bytes
    provider: str
    model: str
    duration_seconds: float
    prompt: str
    has_native_audio: bool = True
    metadata: dict[str, str] | None = None


class VideoShotProvider(Protocol):
    name: str
    model: str

    def generate_shot(
        self, request: VideoShotRequest, *, confirm_paid: bool, use_cache: bool = True
    ) -> VideoShotResult: ...
