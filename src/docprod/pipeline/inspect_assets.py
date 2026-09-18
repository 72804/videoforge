from __future__ import annotations

from dataclasses import dataclass

from docprod.exceptions import ZeroPlaceholderError
from docprod.models.scene import Scene, ScenePlan
from docprod.render.still import resolve_scene_visual
from docprod.stock.models import StockSourceManifest
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths

KIND_LABELS = {
    "stock_video": "pexels_video",
    "generated_still": "openai_image",
    "local_graphic": "local_graphic",
    "local_map": "local_map_animation",
}


@dataclass(frozen=True)
class AssetInspectionRow:
    scene_id: str
    strategy_requested: str
    source_type: str
    source_label: str
    artifact_path: str
    effect_requested: str
    provider: str


def _provider_for(paths: ProjectPaths, scene: Scene, kind: str) -> str:
    if kind != "stock_video":
        if kind == "generated_still":
            return "openai"
        if kind in {"local_graphic", "local_map"}:
            return "local"
        return ""
    meta_path = paths.stock_source_meta(scene.id)
    if not meta_path.is_file():
        return "pexels"
    try:
        meta = load_model(meta_path, StockSourceManifest)
    except (OSError, ValueError):
        return "pexels"
    return meta.provider


def inspect_assets(paths: ProjectPaths, plan: ScenePlan) -> list[AssetInspectionRow]:
    rows: list[AssetInspectionRow] = []
    for scene in plan.scenes:
        visual = resolve_scene_visual(paths, scene)
        if visual is None:
            source_type = "placeholder"
            source_label = "placeholder"
            artifact = ""
            provider = ""
        else:
            source_type = visual.kind
            if visual.kind == "generated_still" and visual.strategy_rendered == (
                "ai_image_keyframe_preview"
            ):
                source_label = "openai_image_keyframe"
            elif visual.kind == "local_graphic":
                source_label = visual.strategy_rendered or "local_graphic"
            else:
                source_label = KIND_LABELS.get(visual.kind, visual.kind)
            artifact = str(visual.path)
            provider = _provider_for(paths, scene, visual.kind)
        rows.append(
            AssetInspectionRow(
                scene_id=scene.id,
                strategy_requested=scene.asset_strategy.value,
                source_type=source_type,
                source_label=source_label,
                artifact_path=artifact,
                effect_requested=scene.effect.value,
                provider=provider,
            )
        )
    return rows


def placeholder_scene_ids(rows: list[AssetInspectionRow]) -> list[str]:
    return [row.scene_id for row in rows if row.source_type == "placeholder"]


def require_zero_placeholders(paths: ProjectPaths, plan: ScenePlan) -> list[AssetInspectionRow]:
    rows = inspect_assets(paths, plan)
    missing = placeholder_scene_ids(rows)
    if missing:
        raise ZeroPlaceholderError(
            "Placeholder visuals remain for: " + ", ".join(missing)
        )
    return rows
