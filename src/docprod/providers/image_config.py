from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from docprod.config import Settings, get_settings


class ImageGenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "openai"
    model: str = "gpt-image-2.5-flare"
    size: str = "1536x864"
    quality: str = "medium"
    output_format: str = "jpeg"

    @field_validator("provider", "model", "size", "quality", "output_format")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("size")
    @classmethod
    def _size_shape(cls, value: str) -> str:
        width_s, sep, height_s = value.partition("x")
        if sep != "x":
            raise ValueError("size must look like WIDTHxHEIGHT")
        width, height = int(width_s), int(height_s)
        if width < 16 or height < 16:
            raise ValueError("image size is too small")
        if width % 16 or height % 16:
            raise ValueError("image width and height must be divisible by 16")
        return value

    @property
    def width(self) -> int:
        return int(self.size.split("x", 1)[0])

    @property
    def height(self) -> int:
        return int(self.size.split("x", 1)[1])

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ImageGenerationConfig:
        cfg = settings or get_settings()
        return cls(
            provider=cfg.image_provider,
            model=cfg.openai_image_model,
            size=cfg.openai_image_size,
            quality=cfg.openai_image_quality,
            output_format=cfg.openai_image_output_format,
        )


class GeneratedImageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    provider: str
    model: str
    scene_id: str
    prompt: str
    size: str
    quality: str
    output_format: str
    seed_requested: int | None = None
    source_scene_hash: str
    request_hash: str
    output_path: str
    output_sha256: str
    revised_prompt: str | None = None
    usage: dict[str, int | float | str] | None = None
    generation_status: str
    cache_hit: bool = False
    elapsed_seconds: float | None = None
    note: str | None = None
