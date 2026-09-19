from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.production.grouping import group_asset_units, saved_generation_count

AI = AssetStrategy.ai_image_to_video
ST = AssetStrategy.stock_video


def _scene(
    n: int, strategy: AssetStrategy, subject: str, start: float, chapter: str = "A"
) -> Scene:
    prompt = "p" if strategy in {AssetStrategy.ai_image, AI} else None
    return Scene(
        id=f"scene_{n:04d}",
        start=start,
        end=start + 3.0,
        duration=3.0,
        narration="x",
        visual_intent=subject,
        asset_strategy=strategy,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle="x",
        generation=GenerationSpec(image_prompt=prompt),
        metadata={
            "visual_subject": subject,
            "chapter": chapter,
            "semantic_intent_id": subject,
        },
    )


def test_adjacent_split_ai_video_grouped_unrelated_not() -> None:
    scenes = [
        _scene(5, AI, "inventory barrel scale", 0),
        _scene(6, AI, "inventory barrel scale", 3),
        _scene(7, ST, "water syrup detail", 6),
        _scene(8, ST, "water syrup detail", 9),
        _scene(9, AI, "other truck loading", 12),
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=15.0)
    units = group_asset_units(plan)
    assert len(plan.scenes) == 5
    ids = [unit.scene_ids for unit in units]
    assert ["scene_0005", "scene_0006"] in ids
    assert ["scene_0007", "scene_0008"] in ids
    assert ["scene_0009"] in ids
    assert saved_generation_count(plan, units) == 1


def test_chapter_change_not_grouped() -> None:
    scenes = [
        _scene(1, ST, "warehouse", 0, chapter="A"),
        _scene(2, ST, "warehouse", 3, chapter="B"),
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=6.0)
    units = group_asset_units(plan)
    assert len(units) == 2
