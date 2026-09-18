from __future__ import annotations

import pytest

from docprod.audio.align import align_script_to_whisper
from docprod.audio.models import WhisperWord
from docprod.exceptions import AlignmentQualityError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan


def _plan(*texts: str) -> ScenePlan:
    scenes = []
    cursor = 0.0
    for index, text in enumerate(texts, start=1):
        end = cursor + 1.0
        scenes.append(
            Scene(
                id=f"scene_{index:04d}",
                start=cursor,
                end=end,
                duration=1.0,
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
        cursor = end
    return ScenePlan(project_id="tiny", scenes=scenes, total_duration=cursor)


def _words(pairs: list[tuple[str, float, float]]) -> list[WhisperWord]:
    return [WhisperWord(word=word, start=start, end=end) for word, start, end in pairs]


def test_exact_and_punctuation_alignment() -> None:
    plan = _plan("Bir adam yürüdü.", "Araba durdu.")
    whisper = _words(
        [
            ("Bir", 0.0, 0.2),
            ("adam", 0.2, 0.4),
            ("yürüdü", 0.4, 0.8),
            ("Araba", 0.9, 1.2),
            ("durdu", 1.2, 1.5),
        ]
    )
    report = align_script_to_whisper(plan, whisper, language="tr")
    assert report.match_fraction == 1.0
    assert report.canonical_word_count == 5
    assert all(token.status == "matched" for token in report.tokens)


def test_case_and_minor_transcription_difference() -> None:
    plan = _plan("İstanbul'daki tren istasyonu boştu.")
    whisper = _words(
        [
            ("istanbuldaki", 0.0, 0.4),
            ("tren", 0.4, 0.6),
            ("istasyonu", 0.6, 0.9),
            ("boştu", 0.9, 1.2),
        ]
    )
    report = align_script_to_whisper(plan, whisper, language="turkish")
    assert report.matched_word_count >= 3
    assert report.language == "turkish"


def test_low_alignment_blocks() -> None:
    plan = _plan("Bir adam yürüdü ve durdu tekrar burada.")
    whisper = _words([("hello", 0.0, 0.2), ("world", 0.2, 0.4)])
    with pytest.raises(AlignmentQualityError):
        align_script_to_whisper(plan, whisper, language="tr")
    report = align_script_to_whisper(plan, whisper, language="tr", require_quality=False)
    assert report.quality_passed is False
    assert report.match_fraction < 0.95


def test_isolated_missing_word_interpolates() -> None:
    plan = _plan("Bir adam yürüdü.")
    whisper = _words([("Bir", 0.0, 0.2), ("yürüdü", 0.5, 0.8)])
    report = align_script_to_whisper(plan, whisper, language="tr", require_quality=False)
    middle = report.tokens[1]
    assert middle.text.lower().startswith("adam")
    if report.interpolated_word_count:
        assert middle.interpolated is True
        assert middle.start is not None and middle.end is not None
