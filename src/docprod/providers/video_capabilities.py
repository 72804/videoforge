from __future__ import annotations

from dataclasses import dataclass

from docprod.providers.pricing import VEO_LITE_720P_USD_PER_SEC


@dataclass(frozen=True)
class VideoModelCapabilities:
    model_id: str
    image_to_video: bool
    native_audio: bool
    negative_prompt: bool
    duration_options: tuple[int, ...]
    resolution_options: tuple[str, ...]
    aspect_ratios: tuple[str, ...]
    reference_images: bool = False
    last_frame: bool = False
    seed: bool = False
    max_outputs: int = 1
    max_prompt_chars: int = 1024
    provider: str = "google"
    text_to_video: bool | None = None
    character_consistency: bool | None = None
    dialogue: bool | None = None
    lip_sync: bool | None = None
    performance_transfer: bool | None = None
    driving_video: bool | None = None
    camera_control: bool | None = None
    max_duration_seconds: int | None = None
    first_frame: bool | None = None
    price_mode: str | None = None
    price_value: float | None = None
    quality_tier: str | None = None
    speed_tier: str | None = None


VEO_LITE_PREVIEW = VideoModelCapabilities(
    model_id="veo-3.1-lite-generate-preview",
    image_to_video=True,
    native_audio=True,
    negative_prompt=False,
    duration_options=(8,),
    resolution_options=("720p",),
    aspect_ratios=("16:9",),
    reference_images=False,
    last_frame=False,
    seed=False,
    max_outputs=1,
    max_prompt_chars=1024,
    provider="google",
    text_to_video=False,
    first_frame=True,
    max_duration_seconds=8,
    price_mode="per_second",
    price_value=VEO_LITE_720P_USD_PER_SEC,
    quality_tier="economy",
    speed_tier="fast",
)

_REGISTRY = {VEO_LITE_PREVIEW.model_id: VEO_LITE_PREVIEW}


def capabilities_for(model_id: str) -> VideoModelCapabilities:
    known = _REGISTRY.get(model_id)
    if known is not None:
        return known
    return VideoModelCapabilities(
        model_id=model_id,
        image_to_video=True,
        native_audio=True,
        negative_prompt=False,
        duration_options=(8,),
        resolution_options=("720p",),
        aspect_ratios=("16:9",),
        max_outputs=1,
        max_prompt_chars=1024,
    )
