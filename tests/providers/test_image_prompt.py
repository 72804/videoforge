from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene
from docprod.providers.image_prompt import DOCUMENTARY_STYLE, build_documentary_image_prompt


def _scene(**kwargs: object) -> Scene:
    payload = {
        "id": "scene_0003",
        "start": 0.0,
        "end": 4.0,
        "duration": 4.0,
        "narration": "Three dogs wait beside an abandoned ATM.",
        "visual_intent": "Wide shot of three dogs at a night-time cash machine.",
        "asset_strategy": AssetStrategy.ai_image,
        "effect": VisualEffect.slow_push_in,
        "transition": TransitionType.cut,
        "mood": Mood.mysterious,
        "subtitle": "Three dogs wait",
        "generation": GenerationSpec(image_prompt="three dogs beside an ATM at night"),
        "metadata": {"primary_category": "crime"},
    }
    payload.update(kwargs)
    return Scene.model_validate(payload)


def test_prompt_preserves_concrete_counts() -> None:
    prompt = build_documentary_image_prompt(_scene())
    assert "three dogs" in prompt.lower()
    assert "ATM" in prompt or "atm" in prompt.lower()
    assert "child" not in prompt.lower()
    assert "red jacket" not in prompt.lower()


def test_prompt_includes_documentary_style_and_avoidance() -> None:
    prompt = build_documentary_image_prompt(_scene())
    assert "photorealistic cinematic documentary" in prompt
    assert DOCUMENTARY_STYLE in prompt
    assert "no watermark" in prompt.lower() or "watermark" in prompt.lower()
    assert "Moody practical lighting" in prompt
    assert "fantasy" in prompt.lower() or "advertising" in prompt.lower()
