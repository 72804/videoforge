from __future__ import annotations

from docprod.graphics.data import INFO_GRAPHIC_KINDS
from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.production import AssetPlan, AssetUnit
from docprod.production.balance import NAMED, _apply_strategy

INFO_GRAPHIC_UNIT_IDS = frozenset({"au_0033", "au_0034", "au_0044", "au_0051"})


def is_named_person_scene(scene: Scene) -> bool:
    blob = (
        f"{scene.narration} {scene.visual_intent} {scene.metadata.get('visual_subject')}"
    ).casefold()
    return any(name in blob for name in NAMED)


def is_information_graphic_unit(unit: AssetUnit, scene: Scene) -> bool:
    return unit.asset_unit_id in INFO_GRAPHIC_UNIT_IDS


def convert_info_graphic_units(
    plan: ScenePlan, asset_plan: AssetPlan
) -> tuple[ScenePlan, AssetPlan]:
    """Move chart/comparison AI stills onto the local graphic engine. No API."""
    scenes = {scene.id: scene for scene in plan.scenes}
    units: list[AssetUnit] = []
    for unit in asset_plan.units:
        first = scenes[unit.scene_ids[0]]
        if not is_information_graphic_unit(unit, first):
            units.append(unit)
            continue
        for scene_id in unit.scene_ids:
            converted = _apply_strategy(
                scenes[scene_id],
                AssetStrategy.generated_graphic,
                "review_info_graphic_local",
            )
            meta = dict(converted.metadata)
            meta["graphic_kind"] = INFO_GRAPHIC_KINDS.get(
                unit.asset_unit_id, "barrel_uncertainty"
            )
            meta["asset_unit_id"] = unit.asset_unit_id
            meta["graphic_brief"] = unit.visual_concept
            scenes[scene_id] = converted.model_copy(update={"metadata": meta})
        units.append(
            unit.model_copy(
                update={
                    "source_strategy": AssetStrategy.generated_graphic,
                    "generation_required": False,
                    "status": "READY_LOCAL",
                    "provider": "local",
                    "estimated_cost": "0",
                    "warnings": [*unit.warnings, "converted_from_ai_image_to_local_graphic"],
                }
            )
        )
    ordered = [scenes[scene.id] for scene in plan.scenes]
    return (
        plan.model_copy(update={"scenes": ordered}),
        asset_plan.model_copy(update={"units": units}),
    )
