from __future__ import annotations

from docprod.audio.align import align_script_to_whisper
from docprod.audio.models import WhisperWord
from docprod.audio.timeline import apply_runtime_timeline, build_runtime_timeline
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan


def test_runtime_timeline_monotonic_keeps_ids() -> None:
    scenes = []
    texts = ["Bir adam yürüdü.", "Araba durdu şimdi."]
    cursor = 0.0
    for index, text in enumerate(texts, start=1):
        scenes.append(
            Scene(
                id=f"scene_{index:04d}",
                start=cursor,
                end=cursor + 2.0,
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
        )
        cursor += 2.0
    plan = ScenePlan(project_id="tiny", scenes=scenes, total_duration=4.0)
    whisper = [
        WhisperWord(word="Bir", start=0.10, end=0.30),
        WhisperWord(word="adam", start=0.30, end=0.50),
        WhisperWord(word="yürüdü", start=0.50, end=0.90),
        WhisperWord(word="Araba", start=1.20, end=1.50),
        WhisperWord(word="durdu", start=1.50, end=1.80),
        WhisperWord(word="şimdi", start=1.80, end=2.10),
    ]
    report = align_script_to_whisper(plan, whisper, language="tr")
    timeline = build_runtime_timeline(plan, report, audio_duration=2.40)
    assert [item.scene_id for item in timeline.scenes] == ["scene_0001", "scene_0002"]
    assert timeline.scenes[0].end == timeline.scenes[1].start
    assert timeline.scenes[1].end == pytest_approx_end(timeline, 2.40)
    runtime = apply_runtime_timeline(plan, timeline)
    assert runtime.scenes[0].id == "scene_0001"
    assert runtime.scenes[0].end == runtime.scenes[1].start
    assert runtime.total_duration == runtime.scenes[-1].end
    assert abs(plan.total_duration - 4.0) < 1e-9


def pytest_approx_end(timeline, audio: float) -> float:
    assert abs(timeline.total_duration - audio) < 0.05
    return timeline.scenes[-1].end
