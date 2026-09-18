from __future__ import annotations

from pathlib import Path

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene
from docprod.providers.image_config import GeneratedImageManifest
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths

IMAGE_STRATEGIES = frozenset({AssetStrategy.ai_image, AssetStrategy.ai_image_to_video})


def image_suffix_for_format(output_format: str) -> str:
    mapping = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp"}
    key = output_format.strip().lower()
    if key not in mapping:
        raise ValueError(f"Unsupported image output_format {output_format!r}")
    return mapping[key]


def still_fit_filter(src_width: int, src_height: int, dst_width: int, dst_height: int) -> str:
    """Cover-fit a still into dst without stretching. Matching AR uses proportional scale."""
    if min(src_width, src_height, dst_width, dst_height) < 2:
        raise ValueError("still fit sizes must be at least 2px")
    src_ar = src_width / src_height
    dst_ar = dst_width / dst_height
    if abs(src_ar - dst_ar) < 1e-4:
        return f"scale={dst_width}:{dst_height}:flags=lanczos"
    return (
        f"scale={dst_width}:{dst_height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={dst_width}:{dst_height}:(iw-ow)/2:(ih-oh)/2"
    )


def still_pixel_normalize_filter() -> str:
    """Map JPEG full-range stills to limited-range yuv420p without a contrast crush."""
    return "scale=in_range=full:out_range=limited:flags=bicubic,format=yuv420p"


def resolve_generated_still(paths: ProjectPaths, scene_id: str) -> tuple[Path, str] | None:
    meta_path = paths.scene_image_meta(scene_id)
    if not meta_path.is_file():
        return None
    try:
        manifest = load_model(meta_path, GeneratedImageManifest)
    except (OSError, ValueError):
        return None
    if manifest.generation_status != "success" or not manifest.output_sha256:
        return None
    candidate = Path(manifest.output_path)
    if not candidate.is_file():
        candidate = (paths.root / manifest.output_path).resolve()
    if not candidate.is_file():
        suffix = image_suffix_for_format(manifest.output_format)
        candidate = paths.scene_image_path(scene_id, suffix=suffix)
    if not candidate.is_file():
        return None
    return candidate, manifest.output_sha256


def resolve_scene_still(paths: ProjectPaths, scene: Scene) -> tuple[Path, str] | None:
    """Return a generated still for ai_image or ai_image_to_video keyframe preview."""
    if scene.asset_strategy not in IMAGE_STRATEGIES:
        return None
    return resolve_generated_still(paths, scene.id)
