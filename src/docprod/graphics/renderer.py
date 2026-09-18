from __future__ import annotations

import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_RENDERER_VERSION, GRAPHIC_WIDTH
from docprod.graphics.document import (
    FORBIDDEN_MARKERS,
    classify_document_layout,
    render_document_graphic,
)
from docprod.graphics.fonts import discover_sans_font
from docprod.graphics.map import DEST, compose_map_still, dest_ring_image
from docprod.graphics.models import GraphicManifest
from docprod.graphics.newspaper import render_newspaper_graphic
from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import atomic_write_bytes, load_model, save_model
from docprod.storage.paths import ProjectPaths

ProgressFn = Callable[[str], None]

GRAPHIC_STRATEGIES = frozenset(
    {AssetStrategy.document, AssetStrategy.map, AssetStrategy.generated_graphic}
)


def graphic_source_hash(scene: Scene, *, seed: int) -> str:
    return content_hash(
        {
            "id": scene.id,
            "narration": scene.narration,
            "visual_intent": scene.visual_intent,
            "strategy": scene.asset_strategy.value,
            "category": scene.metadata.get("primary_category"),
            "seed": seed,
            "renderer": GRAPHIC_RENDERER_VERSION,
            "size": [GRAPHIC_WIDTH, GRAPHIC_HEIGHT],
        }
    )


def requires_local_graphic(scene: Scene) -> bool:
    return scene.asset_strategy in GRAPHIC_STRATEGIES


def _png_bytes(image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _relative(paths: ProjectPaths, output: Path) -> str:
    try:
        return output.resolve().relative_to(paths.root.resolve()).as_posix()
    except ValueError:
        return str(output)


def _load_manifest(path: Path) -> GraphicManifest | None:
    if not path.is_file():
        return None
    try:
        return load_model(path, GraphicManifest)
    except (OSError, ValueError):
        return None


def render_scene_graphic_image(scene: Scene, *, seed: int):
    layout = classify_document_layout(scene)
    salt = f"{seed}:{scene.id}:{GRAPHIC_RENDERER_VERSION}"
    if scene.asset_strategy is AssetStrategy.map:
        still, background, overlay, mask, fields = compose_map_still(scene, seed=salt)
        return "map", "schematic_map", still, fields, overlay, mask, background
    if layout == "newspaper":
        image, fields, variant = render_newspaper_graphic(scene, seed=salt)
        return "newspaper", variant, image, fields, None, None, None
    image, fields, variant = render_document_graphic(scene, seed=salt)
    return "document", variant, image, fields, None, None, None


def execute_generate_graphic(
    paths: ProjectPaths,
    *,
    scene: Scene,
    seed: int,
    force: bool = False,
    progress: ProgressFn | None = None,
) -> GraphicManifest:
    if not requires_local_graphic(scene):
        raise ValueError(f"Scene {scene.id} does not use a local graphic strategy")
    request_hash = graphic_source_hash(scene, seed=seed)
    directory = paths.scene_graphics_dir(scene.id)
    directory.mkdir(parents=True, exist_ok=True)
    is_map = scene.asset_strategy is AssetStrategy.map
    output = paths.scene_map_base(scene.id) if is_map else paths.scene_graphic_png(scene.id)
    meta_path = paths.scene_map_meta(scene.id) if is_map else paths.scene_graphic_meta(scene.id)
    existing = _load_manifest(meta_path)
    if (
        not force
        and existing is not None
        and existing.request_hash == request_hash
        and existing.output_sha256
        and output.is_file()
        and file_sha256(output) == existing.output_sha256
    ):
        existing.cache_hit = True
        if progress:
            progress(f"Skip {scene.id} (cached local graphic)")
        return existing
    started = time.perf_counter()
    graphic_type, variant, image, fields, overlay, mask, background = render_scene_graphic_image(
        scene, seed=seed
    )
    joined = " ".join(fields.values())
    if any(marker.lower() in joined.lower() for marker in FORBIDDEN_MARKERS):
        raise ValueError("Graphic text included a forbidden official marker")
    png = _png_bytes(image)
    atomic_write_bytes(output, png)
    extra: dict[str, object] = {}
    if overlay is not None and mask is not None and background is not None:
        route_path = paths.scene_map_route(scene.id)
        mask_path = paths.scene_map_mask(scene.id)
        ring_path = paths.scene_map_ring(scene.id)
        bg_path = paths.scene_map_bg(scene.id)
        atomic_write_bytes(route_path, _png_bytes(overlay))
        atomic_write_bytes(mask_path, _png_bytes(mask))
        atomic_write_bytes(ring_path, _png_bytes(dest_ring_image()))
        atomic_write_bytes(bg_path, _png_bytes(background))
        extra = {
            "route_path": _relative(paths, route_path),
            "mask_path": _relative(paths, mask_path),
            "ring_path": _relative(paths, ring_path),
            "bg_path": _relative(paths, bg_path),
            "dest": list(DEST),
        }
    digest = file_sha256(output)
    manifest = GraphicManifest(
        scene_id=scene.id,
        graphic_type=graphic_type,
        renderer_version=GRAPHIC_RENDERER_VERSION,
        source_scene_hash=request_hash,
        request_hash=request_hash,
        output_sha256=digest,
        output_path=_relative(paths, output),
        text_fields=fields,
        layout_variant=variant,
        font=str(discover_sans_font()),
        width=GRAPHIC_WIDTH,
        height=GRAPHIC_HEIGHT,
        cache_hit=False,
        elapsed_seconds=round(time.perf_counter() - started, 3),
        extra=extra,
    )
    save_model(meta_path, manifest)
    if progress:
        progress(f"Wrote {output} in {manifest.elapsed_seconds:.3f}s")
    return manifest


def execute_generate_graphics(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    seed: int,
    force: bool = False,
    scene_id: str | None = None,
    progress: ProgressFn | None = None,
) -> list[GraphicManifest]:
    results: list[GraphicManifest] = []
    for scene in plan.scenes:
        if scene_id is not None and scene.id != scene_id:
            continue
        if not requires_local_graphic(scene):
            continue
        results.append(
            execute_generate_graphic(
                paths, scene=scene, seed=seed, force=force, progress=progress
            )
        )
    return results
