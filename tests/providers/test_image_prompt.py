from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene
from docprod.providers.image_prompt import (
    DOCUMENTARY_STYLE,
    SINGLE_FRAME,
    build_documentary_image_prompt,
    collect_unique_scene_facts,
    is_semantically_thin,
)


def _scene(**kwargs: object) -> Scene:
    payload = {
        "id": "scene_0003",
        "start": 0.0,
        "end": 4.0,
        "duration": 4.0,
        "narration": "Three dogs wait beside an abandoned ATM.",
        "visual_intent": (
            "Documentary visual representing: Three dogs wait beside an abandoned ATM."
        ),
        "asset_strategy": AssetStrategy.ai_image,
        "effect": VisualEffect.slow_push_in,
        "transition": TransitionType.cut,
        "mood": Mood.mysterious,
        "subtitle": "Three dogs wait",
        "generation": GenerationSpec(
            image_prompt=(
                "Documentary visual representing: Three dogs wait beside an abandoned ATM. "
                "cinematic documentary reenactment, realistic photography, "
                "natural lighting, 35mm documentary look, 16:9"
            )
        ),
        "metadata": {"primary_category": "crime"},
    }
    payload.update(kwargs)
    return Scene.model_validate(payload)


def test_duplicate_prompt_text_removed() -> None:
    facts = collect_unique_scene_facts(_scene())
    joined = " ".join(facts).lower()
    assert joined.count("three dogs wait beside an abandoned atm") == 1
    prompt = build_documentary_image_prompt(_scene())
    assert prompt.lower().count("three dogs wait beside an abandoned atm") == 1
    assert prompt.count(DOCUMENTARY_STYLE) == 1


def test_unique_visual_information_retained() -> None:
    scene = _scene(
        visual_intent="Wide shot of three dogs at a night-time cash machine.",
        generation=GenerationSpec(image_prompt="three dogs beside an ATM at night, wet pavement"),
    )
    prompt = build_documentary_image_prompt(scene)
    assert "three dogs" in prompt.lower()
    assert "wide shot" in prompt.lower()
    assert "wet pavement" in prompt.lower()


def test_prompt_preserves_concrete_counts() -> None:
    prompt = build_documentary_image_prompt(
        _scene(visual_intent="Wide shot of three dogs at a night-time cash machine.")
    )
    assert "three dogs" in prompt.lower()
    assert "ATM" in prompt or "atm" in prompt.lower()
    assert "child" not in prompt.lower()
    assert "red jacket" not in prompt.lower()


def test_documentary_style_appears_once() -> None:
    prompt = build_documentary_image_prompt(_scene())
    assert prompt.count(DOCUMENTARY_STYLE) == 1
    assert "photorealistic cinematic documentary" in prompt
    assert "no visible text" in prompt.lower()
    assert "Moody practical" not in prompt
    assert "unnaturally dark" in prompt


def test_short_narration_activates_context_assist() -> None:
    previous = _scene(
        id="scene_0005",
        narration="Tomar para ve yırtık bir fotoğraf yere saçıldı.",
        visual_intent="Money and a torn photo on the ground.",
    )
    current = _scene(
        id="scene_0006",
        narration="Durdu.",
        visual_intent="Durdu.",
        metadata={"primary_category": "person"},
    )
    nxt = _scene(
        id="scene_0007",
        narration="Kuzey çıkışına doğru koştu.",
        visual_intent="He ran toward the north exit.",
    )
    assert is_semantically_thin(current) is True
    prompt = build_documentary_image_prompt(
        current, previous_scene=previous, next_scene=nxt
    )
    assert "Context:" in prompt
    assert "Current visual moment:" in prompt
    assert "Depict only the current moment." in prompt
    assert "Durdu." in prompt
    assert "Tomar para" in prompt
    assert "Kuzey çıkışına" in prompt
    lowered = prompt.lower()
    assert lowered.count("tomar para ve yırtık bir fotoğraf yere saçıldı.") == 1
    assert prompt.count(SINGLE_FRAME) == 1
    assert lowered.count("collage") == 1
    assert lowered.count("split screen") == 1


def test_descriptive_narration_skips_neighbor_expansion() -> None:
    previous = _scene(narration="Earlier beat with extra unused context words here.")
    current = _scene()
    nxt = _scene(id="scene_0004", narration="Later beat about something else entirely.")
    assert is_semantically_thin(current) is False
    prompt = build_documentary_image_prompt(
        current, previous_scene=previous, next_scene=nxt
    )
    assert "Context:" not in prompt
    assert "Current visual moment:" not in prompt
    assert "Earlier beat" not in prompt
    assert "Later beat" not in prompt
    assert prompt.count(SINGLE_FRAME) == 1
    assert "three dogs wait beside an abandoned atm" in prompt.lower()


def test_single_frame_constraint_appears_once() -> None:
    prompt = build_documentary_image_prompt(_scene(narration="Durdu.", visual_intent="Durdu."))
    assert prompt.count(SINGLE_FRAME) == 1
    assert prompt.lower().count("contact sheet") == 1
    assert prompt.lower().count("multiple panels") == 1

