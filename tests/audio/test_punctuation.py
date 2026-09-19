from __future__ import annotations

from docprod.audio.chunks import NarrationChunkPlanner
from docprod.audio.script import (
    build_canonical_script,
    fold_token,
    slice_punctuated_words,
    tts_input_text,
)
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan


def _scene(text: str) -> Scene:
    return Scene(
        id="scene_0001",
        start=0.0,
        end=2.0,
        duration=2.0,
        narration=text,
        visual_intent="shot",
        asset_strategy=AssetStrategy.placeholder,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=text,
        metadata={"primary_category": "generic"},
    )


def test_punctuation_survives_into_tts_and_chunks() -> None:
    text = "Adam'ın raporu durdu; envanter, kontrol. Quebec'te."
    plan = ScenePlan(
        project_id="tiny",
        scenes=[_scene(text)],
        total_duration=2.0,
    )
    script = build_canonical_script(plan)
    tts = tts_input_text(script)
    assert "." in tts
    assert "," in tts
    assert ";" in tts
    assert "'" in tts
    manifest = NarrationChunkPlanner().plan(script, plan)
    joined = "".join(chunk.text for chunk in manifest.chunks)
    assert "." in joined and "," in joined and ";" in joined and "'" in joined


def test_only_alignment_fold_strips_punctuation() -> None:
    assert fold_token("durdu.") == "durdu"
    assert "'" not in fold_token("Adam'ın")
    sliced = slice_punctuated_words("Durdu. Sonra gitti.", 0, 1)
    assert "." in sliced
