from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from docprod.models import (
    AssetStrategy,
    GenerationSpec,
    Mood,
    NarrationScript,
    Scene,
    ScenePlan,
    TransitionType,
    Utterance,
    VisualEffect,
    WordTiming,
)


def _scene(**overrides: object) -> Scene:
    data: dict[str, object] = {
        "id": "scene_0001",
        "start": 0.0,
        "end": 3.0,
        "duration": 3.0,
        "narration": "A train arrives.",
        "visual_intent": "Train arriving at a platform",
        "asset_strategy": AssetStrategy.placeholder,
        "effect": VisualEffect.none,
        "transition": TransitionType.cut,
        "mood": Mood.neutral,
        "subtitle": "A train arrives.",
    }
    data.update(overrides)
    return Scene.model_validate(data)


def test_scene_duration_mismatch_rejected() -> None:
    with pytest.raises(ValidationError, match="duration"):
        _scene(duration=2.0)


def test_invalid_scene_id_rejected() -> None:
    with pytest.raises(ValidationError, match="scene_"):
        _scene(id="shot_0001")


def test_scene_plan_overlap_rejected() -> None:
    a = _scene(id="scene_0001", start=0.0, end=3.0, duration=3.0)
    b = _scene(id="scene_0002", start=2.5, end=5.0, duration=2.5)
    with pytest.raises(ValidationError, match="overlap"):
        ScenePlan(project_id="demo", scenes=[a, b], total_duration=5.0)


def test_scene_plan_duplicate_ids_rejected() -> None:
    a = _scene(id="scene_0001", start=0.0, end=3.0, duration=3.0)
    b = _scene(id="scene_0001", start=3.0, end=6.0, duration=3.0)
    with pytest.raises(ValidationError, match="duplicate"):
        ScenePlan(project_id="demo", scenes=[a, b], total_duration=6.0)


def test_scene_plan_touching_ok() -> None:
    a = _scene(id="scene_0001", start=0.0, end=3.0, duration=3.0)
    b = _scene(id="scene_0002", start=3.0, end=6.0, duration=3.0)
    plan = ScenePlan(project_id="demo", scenes=[a, b], total_duration=6.0)
    assert plan.total_duration == 6.0


def test_ai_image_requires_prompt() -> None:
    with pytest.raises(ValidationError, match="image_prompt"):
        _scene(asset_strategy=AssetStrategy.ai_image, generation=GenerationSpec())


def test_placeholder_does_not_require_prompt() -> None:
    scene = _scene(asset_strategy=AssetStrategy.placeholder)
    assert scene.generation.image_prompt is None


def test_example_scene_shape() -> None:
    scene = Scene(
        id="scene_0047",
        start=126.4,
        end=130.1,
        duration=3.7,
        narration="He lived alone except for three dogs that followed him everywhere.",
        visual_intent="Man arriving home accompanied by exactly three dogs",
        asset_strategy=AssetStrategy.ai_image,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.ominous,
        subtitle="He lived alone except for three dogs that followed him everywhere.",
        generation=GenerationSpec(
            image_prompt="cinematic documentary reenactment of a man with three dogs",
            negative_prompt=None,
            motion_prompt=None,
            seed=12345,
        ),
        sources=[],
        metadata={},
    )
    dumped = scene.model_dump(mode="json")
    assert dumped["asset_strategy"] == "ai_image"
    assert dumped["id"] == "scene_0047"


def test_narration_script_rejects_overlap() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        NarrationScript(
            language="en",
            full_text="Hello world",
            utterances=[
                Utterance(
                    id="utt_1",
                    text="Hello",
                    start=0.0,
                    end=1.2,
                    words=[WordTiming(word="Hello", start=0.0, end=1.2)],
                ),
                Utterance(id="utt_2", text="world", start=1.0, end=2.0, words=[]),
            ],
        )


def test_timezone_naive_project_rejected() -> None:
    from docprod.models.project import Project

    with pytest.raises(ValidationError):
        Project(
            id="demo",
            title="Demo",
            language="en",
            target_duration_seconds=30,
            created_at=datetime.now(),
            updated_at=datetime.now(UTC),
        )


def test_empty_narration_rejected_unless_visual_bridge() -> None:
    with pytest.raises(ValidationError, match="narration"):
        _scene(narration="")
    bridge = _scene(narration="", subtitle="", metadata={"visual_bridge": True})
    assert bridge.metadata["visual_bridge"] is True
