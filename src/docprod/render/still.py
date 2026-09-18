from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docprod.graphics.models import GraphicManifest
from docprod.graphics.renderer import GRAPHIC_STRATEGIES
from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene
from docprod.providers.image_config import GeneratedImageManifest
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths

IMAGE_STRATEGIES = frozenset({AssetStrategy.ai_image, AssetStrategy.ai_image_to_video})


@dataclass(frozen=True)
class VisualSource:
    path: Path
    sha256: str
    kind: str
    strategy_rendered: str
    map_route: Path | None = None
    map_mask: Path | None = None
    map_ring: Path | None = None
    map_bg: Path | None = None
    dest: tuple[int, int] | None = None


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


def _graphic_file(paths: ProjectPaths, relative: object, fallback: Path) -> Path:
    if isinstance(relative, str) and relative:
        candidate = Path(relative)
        if candidate.is_file():
            return candidate
        nested = (paths.root / relative).resolve()
        if nested.is_file():
            return nested
    return fallback


def resolve_local_graphic(paths: ProjectPaths, scene: Scene) -> VisualSource | None:
    if scene.asset_strategy not in GRAPHIC_STRATEGIES:
        return None
    is_map = scene.asset_strategy is AssetStrategy.map
    meta_path = paths.scene_map_meta(scene.id) if is_map else paths.scene_graphic_meta(scene.id)
    png = paths.scene_map_base(scene.id) if is_map else paths.scene_graphic_png(scene.id)
    if not meta_path.is_file():
        return None
    try:
        manifest = load_model(meta_path, GraphicManifest)
    except (OSError, ValueError):
        return None
    output = _graphic_file(paths, manifest.output_path, png)
    if not output.is_file() or not manifest.output_sha256:
        return None
    extra = manifest.extra or {}
    dest_raw = extra.get("dest")
    dest = None
    if isinstance(dest_raw, list) and len(dest_raw) == 2:
        dest = (int(dest_raw[0]), int(dest_raw[1]))
    if is_map:
        return VisualSource(
            path=output,
            sha256=manifest.output_sha256,
            kind="local_map",
            strategy_rendered="map",
            map_route=_graphic_file(
                paths, extra.get("route_path"), paths.scene_map_route(scene.id)
            ),
            map_mask=_graphic_file(paths, extra.get("mask_path"), paths.scene_map_mask(scene.id)),
            map_ring=_graphic_file(paths, extra.get("ring_path"), paths.scene_map_ring(scene.id)),
            map_bg=_graphic_file(paths, extra.get("bg_path"), paths.scene_map_bg(scene.id)),
            dest=dest,
        )
    rendered = "newspaper" if manifest.graphic_type == "newspaper" else "document"
    return VisualSource(
        path=output,
        sha256=manifest.output_sha256,
        kind="local_graphic",
        strategy_rendered=rendered,
    )


def resolve_scene_visual(paths: ProjectPaths, scene: Scene) -> VisualSource | None:
    """AI still/keyframe, then local graphic/map, else None (placeholder)."""
    if scene.asset_strategy in IMAGE_STRATEGIES:
        still = resolve_generated_still(paths, scene.id)
        if still is not None:
            kind = (
                "ai_image_keyframe_preview"
                if scene.asset_strategy is AssetStrategy.ai_image_to_video
                else "ai_image"
            )
            return VisualSource(
                path=still[0],
                sha256=still[1],
                kind="generated_still",
                strategy_rendered=kind,
            )
        return None
    return resolve_local_graphic(paths, scene)
