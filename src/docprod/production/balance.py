from __future__ import annotations

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.planning.models import round_time
from docprod.planning.planner import image_prompt_for, motion_prompt_for

KEEP_GRAPHIC = (
    "milyon",
    "million",
    "ton",
    "pound",
    "cad",
    "dolar",
    "yüzde",
    "kota",
    "tazminat",
    "ceza",
    "hapis",
    "mahkeme",
    "timeline",
    "zaman",
    "1966",
    "2000",
    "2002",
    "2003",
    "2013",
    "2016",
    "2022",
    "9 milyon",
    "18",
    "6 milyon",
    "federasyon",
    "rezerv",
)
ATMOSPHERE = (
    "depo",
    "fıçı",
    "warehouse",
    "barrel",
    "kamyon",
    "truck",
    "koridor",
    "orman",
    "inspection",
    "denetim",
    "worker",
    "üretim",
    "sap",
    "yol",
    "transport",
    "şeker kamp",
)
NAMED = (
    "michel gauvreau",
    "gauvreau",
    "vallières",
    "vallieres",
    "avik caron",
    "st-pierre",
    "st pierre",
    "jean lord",
    "étienne",
    "etienne",
    "raymond",
)


def _blob(scene: Scene) -> str:
    meta = scene.metadata
    return " ".join(
        [
            scene.narration,
            scene.visual_intent,
            str(meta.get("visual_subject") or ""),
            str(meta.get("graphic_brief") or ""),
            str(meta.get("visual_purpose") or ""),
        ]
    ).casefold()


def _named_person(scene: Scene) -> bool:
    text = _blob(scene)
    return any(name in text for name in NAMED)


def _keep_information_graphic(scene: Scene) -> bool:
    from docprod.planning.visual_policy import explicit_explainer_requested

    return explicit_explainer_requested(scene)


def _mostly_atmosphere(text: str) -> bool:
    hits = sum(1 for token in ATMOSPHERE if token in text)
    info = sum(1 for token in KEEP_GRAPHIC if token in text)
    return hits >= 2 and info == 0


def _convert_target(scene: Scene) -> AssetStrategy:
    text = _blob(scene)
    movement = str(scene.metadata.get("movement_need") or "low")
    if _named_person(scene):
        return AssetStrategy.archive_image
    if movement == "high":
        return AssetStrategy.stock_video
    if any(token in text for token in ATMOSPHERE):
        if movement in {"none", "low"} and (
            "depo" in text or "fıçı" in text or "interior" in text
        ):
            return AssetStrategy.ai_image
        return AssetStrategy.stock_video
    return AssetStrategy.ai_image


def rebalance_scene_plan(plan: ScenePlan) -> ScenePlan:
    """Deterministic mix correction. Semantics still win over quotas."""
    scenes: list[Scene] = []
    graphic_run = 0
    for scene in plan.scenes:
        strategy = scene.asset_strategy
        if strategy in {
            AssetStrategy.generated_graphic,
            AssetStrategy.document,
            AssetStrategy.map,
            AssetStrategy.text_card,
        }:
            graphic_run += 1
        else:
            graphic_run = 0
        converted = scene
        if strategy in {
            AssetStrategy.generated_graphic,
            AssetStrategy.document,
            AssetStrategy.map,
            AssetStrategy.text_card,
        } and not _keep_information_graphic(scene):
            converted = _apply_strategy(
                scene, _convert_target(scene), "balance_disable_explainer_default"
            )
            graphic_run = 0
        elif (
            strategy
            in {
                AssetStrategy.generated_graphic,
                AssetStrategy.document,
            }
            and graphic_run >= 3
            and not _named_person(scene)
        ):
            alt = (
                AssetStrategy.stock_video
                if graphic_run % 2 == 1
                else AssetStrategy.ai_image
            )
            if _named_person(scene):
                alt = AssetStrategy.archive_image
            converted = _apply_strategy(scene, alt, "balance_break_graphic_run")
            graphic_run = 0
        scenes.append(converted)
    return plan.model_copy(update={"scenes": scenes})


def _apply_strategy(scene: Scene, strategy: AssetStrategy, reason: str) -> Scene:
    metadata = dict(scene.metadata)
    metadata["balance_reason"] = reason
    metadata["balance_from"] = scene.asset_strategy.value
    generation = scene.generation
    if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
        intent = scene.visual_intent
        generation = scene.generation.model_copy(
            update={
                "image_prompt": image_prompt_for(
                    str(metadata.get("image_prompt_seed") or intent)
                ),
                "motion_prompt": (
                    motion_prompt_for(str(metadata.get("visual_action") or ""), [])
                    if strategy is AssetStrategy.ai_image_to_video
                    else None
                ),
            }
        )
    elif strategy not in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
        if strategy in {AssetStrategy.stock_video, AssetStrategy.archive_image}:
            generation = scene.generation.model_copy(
                update={"image_prompt": None, "motion_prompt": None}
            )
    return scene.model_copy(
        update={
            "asset_strategy": strategy,
            "generation": generation,
            "metadata": metadata,
            "duration": round_time(scene.duration),
        }
    )
