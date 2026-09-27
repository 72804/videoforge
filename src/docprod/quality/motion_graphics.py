from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docprod.quality.enums import ProductionBackend


class MotionGraphicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    caption: str = ""
    character_id: str = ""
    duration_seconds: float = 2.0


class MotionGraphicsSpec(BaseModel):
    """Director can request effects. Router picks local FFmpeg unless optional AE is enabled."""

    model_config = ConfigDict(extra="forbid")

    requests: list[MotionGraphicsRequest] = Field(default_factory=list)
    preferred_backend: ProductionBackend = ProductionBackend.LOCAL_FFMPEG
    allow_optional_motion_designer: bool = False


MOTION_GRAPHIC_KINDS: tuple[str, ...] = (
    "cold_open",
    "character_intro",
    "punchline_caption",
    "freeze_frame",
    "transition",
    "episode_title",
    "end_card",
)


def route_motion_graphics(spec: MotionGraphicsSpec) -> ProductionBackend:
    if (
        spec.allow_optional_motion_designer
        and spec.preferred_backend is ProductionBackend.OPTIONAL_PRODUCTION_BACKEND
    ):
        return ProductionBackend.OPTIONAL_PRODUCTION_BACKEND
    return ProductionBackend.LOCAL_FFMPEG
