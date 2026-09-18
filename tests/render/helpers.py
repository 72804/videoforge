from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan


def mini_scene(
    scene_id: str,
    start: float,
    end: float,
    *,
    subtitle: str = "Hello",
    effect: VisualEffect = VisualEffect.slow_push_in,
    strategy: AssetStrategy = AssetStrategy.placeholder,
    transition: TransitionType = TransitionType.cut,
) -> Scene:
    duration = round(end - start, 4)
    return Scene(
        id=scene_id,
        start=start,
        end=end,
        duration=duration,
        narration=subtitle or "hold",
        visual_intent="Test card",
        asset_strategy=strategy,
        effect=effect,
        transition=transition,
        mood=Mood.neutral,
        subtitle=subtitle,
        metadata={"primary_category": "generic"},
    )


def mini_plan(*scenes: Scene, project_id: str = "tiny") -> ScenePlan:
    items = list(scenes)
    return ScenePlan(
        project_id=project_id,
        scenes=items,
        total_duration=items[-1].end if items else 0.0,
    )
