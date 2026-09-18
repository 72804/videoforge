from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from docprod.models.enums import AssetStrategy, TransitionType, VisualEffect
from docprod.storage.paths import RENDERER_VERSION


class PreviewRenderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "preview_720p_v1"
    renderer_version: str = RENDERER_VERSION
    width: int = 1280
    height: int = 720
    fps: int = 30
    video_codec: str = "libx264"
    pixel_format: str = "yuv420p"
    crf: int = 23
    preset: str = "veryfast"
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    audio_sample_rate: int = 48000
    burn_subtitles: bool = True
    segment_workers: int = 2
    motion_oversample_factor: int = 1

    @field_validator("name", "renderer_version", "video_codec", "preset")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _validate(self) -> PreviewRenderProfile:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.width % 2 or self.height % 2:
            raise ValueError("width and height must be even")
        if self.fps < 8 or self.fps > 60:
            raise ValueError("fps must be between 8 and 60")
        if self.segment_workers < 1:
            raise ValueError("segment_workers must be >= 1")
        if self.crf < 0 or self.crf > 51:
            raise ValueError("crf out of range")
        if self.audio_sample_rate < 8000:
            raise ValueError("audio_sample_rate too low")
        if self.motion_oversample_factor < 1:
            raise ValueError("motion_oversample_factor must be >= 1")
        return self


TINY_TEST_PROFILE = PreviewRenderProfile(
    name="test_tiny",
    width=160,
    height=120,
    fps=10,
    crf=28,
    preset="ultrafast",
    segment_workers=1,
)


class SegmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    input_hash: str
    duration: float
    frame_count: int
    strategy: AssetStrategy
    effect_requested: VisualEffect
    effect_rendered: VisualEffect
    fallback_used: bool
    transition_requested: TransitionType
    transition_rendered: TransitionType
    transition_fallback: bool
    cache_hit: bool = False
    ffmpeg_command_summary: str = ""
    output_sha256: str | None = None
    source_asset: str | None = None
    strategy_requested: AssetStrategy | None = None
    strategy_rendered: str | None = None
    effect_override_reason: str | None = None


class RenderManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    renderer_version: str
    project_id: str
    scene_plan_hash: str
    input_hash: str
    render_profile: PreviewRenderProfile
    scene_count: int
    expected_duration: float
    actual_duration: float | None = None
    width: int
    height: int
    fps: int
    subtitle_srt: str
    subtitle_ass: str
    final_output: str
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    font_path: str | None = None
    concat_strategy: str = "concat_demuxer_copy_then_encode_subtitles_audio"
    fallback_count: int = 0
    segments: list[SegmentRecord] = Field(default_factory=list)
    final_output_sha256: str | None = None
