from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.planning.visual_bible import (
    derive_visual_bible,
    scene_includes_protagonist,
)
from docprod.providers.image_prompt import build_documentary_image_prompt


def _scene(
    scene_id: str,
    narration: str,
    *,
    start: float,
    strategy: AssetStrategy = AssetStrategy.ai_image,
    category: str = "person",
    extra: str | None = None,
) -> Scene:
    return Scene(
        id=scene_id,
        start=start,
        end=start + 1.0,
        duration=1.0,
        narration=narration,
        visual_intent=extra or narration,
        asset_strategy=strategy,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        generation=GenerationSpec(image_prompt=narration)
        if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
        else GenerationSpec(),
        metadata={"primary_category": category},
    )


def test_continuity_only_where_protagonist_appears() -> None:
    plan = ScenePlan(
        project_id="demo",
        scenes=[
            _scene("scene_0001", "Koyu paltolu bir adam son vagondan indi.", start=0.0),
            _scene(
                "scene_0002",
                "Bankın üzerinde unutulmuş bir evrak çantası duruyordu.",
                start=1.0,
                category="generic",
            ),
            _scene(
                "scene_0003",
                "Adam çantayı aldı ve yürüdü.",
                start=2.0,
                strategy=AssetStrategy.ai_image_to_video,
            ),
            _scene(
                "scene_0004",
                "Polis memurları perona girdi.",
                start=3.0,
                category="police",
            ),
        ],
        total_duration=4.0,
    )
    bible = derive_visual_bible(plan)
    assert "dark practical coat" in (bible.protagonist_description or "")
    assert "ethnicity" not in (bible.protagonist_description or "").lower()
    assert scene_includes_protagonist(plan.scenes[0], bible) is True
    assert scene_includes_protagonist(plan.scenes[1], bible, previous_had_protagonist=True) is False
    assert scene_includes_protagonist(plan.scenes[2], bible, previous_had_protagonist=True) is True
    assert scene_includes_protagonist(plan.scenes[3], bible, previous_had_protagonist=True) is False
    man = build_documentary_image_prompt(plan.scenes[0], bible=bible, include_protagonist=True)
    bag = build_documentary_image_prompt(plan.scenes[1], bible=bible, include_protagonist=False)
    assert "same adult man" in man
    assert "same adult man" not in bag
    assert "evrak çantası" in bag
