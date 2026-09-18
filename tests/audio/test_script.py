from __future__ import annotations

from docprod.audio.script import build_canonical_script, fold_token, tokenize_display
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan


def _scene(scene_id: str, text: str, start: float, end: float) -> Scene:
    return Scene(
        id=scene_id,
        start=start,
        end=end,
        duration=round(end - start, 4),
        narration=text,
        visual_intent="shot",
        asset_strategy=AssetStrategy.placeholder,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=text,
        metadata={"primary_category": "generic"},
    )


def test_canonical_script_is_deterministic_and_maps_spans() -> None:
    plan = ScenePlan(
        project_id="tiny",
        scenes=[
            _scene("scene_0001", "  Bir  adam  yürüdü. ", 0.0, 1.0),
            _scene("scene_0002", "Araba durdu.", 1.0, 2.0),
        ],
        total_duration=2.0,
    )
    first = build_canonical_script(plan)
    second = build_canonical_script(plan)
    assert first.text == second.text == "Bir adam yürüdü. Araba durdu."
    assert first.spans[0].scene_id == "scene_0001"
    assert first.text[first.spans[0].char_start : first.spans[0].char_end] == "Bir adam yürüdü."
    assert first.text[first.spans[1].char_start : first.spans[1].char_end] == "Araba durdu."


def test_turkish_fold_and_tokenize() -> None:
    assert fold_token("İstanbul") == fold_token("istanbul")
    assert tokenize_display("Adam'ın çantası durdu.") == ["Adam'ın", "çantası", "durdu"]
