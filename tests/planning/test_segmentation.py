from __future__ import annotations

from docprod.models.script import TIMING_TOLERANCE
from docprod.planning.segmentation import segment_script
from tests.planning.helpers import PROFILE, script_from, utterance


def _coverage(beats) -> tuple[float, float]:
    return beats[0].start, beats[-1].end


def test_simple_utterance_becomes_one_beat() -> None:
    script = script_from(utterance("u1", "The city was quiet at night.", 0.0, 3.2))
    beats = segment_script(script, PROFILE)
    assert len(beats) == 1
    assert abs(beats[0].duration - 3.2) <= TIMING_TOLERANCE
    assert beats[0].text.startswith("The city")


def test_short_and_medium_beats_merge() -> None:
    script = script_from(
        utterance("u1", "Stop.", 0.0, 1.2),
        utterance("u2", "The man waited on the platform.", 1.2, 5.2),
    )
    beats = segment_script(script, PROFILE)
    assert len(beats) == 1
    assert abs(beats[0].duration - 5.2) <= 1e-3


def test_long_utterance_splits_above_max() -> None:
    text = (
        "The man walked through the station and opened a door then left the hall "
        "and entered another corridor after he grabbed his coat near the stairs."
    )
    script = script_from(utterance("u1", text, 0.0, 11.0, timed=True))
    beats = segment_script(script, PROFILE)
    assert len(beats) >= 2
    for beat in beats:
        assert beat.duration <= PROFILE.max_scene_duration + 0.05
        assert beat.start >= -1e-6
    assert abs(beats[0].start - 0.0) <= 1e-3
    assert abs(beats[-1].end - 11.0) <= 1e-3
    for prev, curr in zip(beats, beats[1:], strict=False):
        assert curr.start >= prev.end - TIMING_TOLERANCE


def test_punctuation_aware_split() -> None:
    first = "Quiet city streets waited."
    second = "Then the man opened the heavy station door and walked inside slowly."
    text = f"{first} {second}"
    script = script_from(utterance("u1", text, 0.0, 9.0, timed=True))
    beats = segment_script(script, PROFILE)
    assert len(beats) >= 2
    assert any("waited." in beat.text or beat.text.endswith("waited.") for beat in beats[:2])


def test_word_timing_split_near_target() -> None:
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    script = script_from(utterance("u1", text, 0.0, 10.5, timed=True))
    beats = segment_script(script, PROFILE)
    assert len(beats) >= 2
    # First cut should land near the target duration.
    assert 2.0 <= beats[0].duration <= 6.0
    assert "split_long_utterance" in beats[0].segmentation_reason or len(beats) > 1


def test_proportional_split_without_word_timings() -> None:
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    script = script_from(utterance("u1", text, 0.0, 10.0, timed=False))
    beats = segment_script(script, PROFILE)
    assert len(beats) >= 2
    assert all("proportional" in beat.segmentation_reason for beat in beats)
    assert abs(beats[-1].end - 10.0) <= 1e-3
    joined = " ".join(beat.text for beat in beats)
    for token in text.split():
        assert token in joined


def test_exact_max_boundary_kept_whole() -> None:
    script = script_from(utterance("u1", "Exactly six seconds of narration here.", 0.0, 6.0))
    beats = segment_script(script, PROFILE)
    assert len(beats) == 1
    assert abs(beats[0].duration - 6.0) <= TIMING_TOLERANCE


def test_short_gap_extends_coverage() -> None:
    script = script_from(
        utterance("u1", "The station was empty.", 0.0, 3.0),
        utterance("u2", "A man arrived later.", 3.3, 6.5),
    )
    beats = segment_script(script, PROFILE)
    for prev, curr in zip(beats, beats[1:], strict=False):
        assert abs(curr.start - prev.end) <= TIMING_TOLERANCE
    assert not any(beat.visual_bridge for beat in beats)
    assert abs(_coverage(beats)[1] - 6.5) <= 1e-3


def test_long_gap_inserts_bridge() -> None:
    script = script_from(
        utterance("u1", "The station was empty.", 0.0, 3.0),
        utterance("u2", "A man arrived later.", 5.5, 8.5),
    )
    beats = segment_script(script, PROFILE)
    bridges = [beat for beat in beats if beat.visual_bridge]
    assert len(bridges) == 1
    assert bridges[0].text == ""
    assert abs(bridges[0].duration - 2.5) <= 0.05
    starts = [beat.start for beat in beats]
    assert starts == sorted(starts)
    for prev, curr in zip(beats, beats[1:], strict=False):
        assert curr.start >= prev.end - TIMING_TOLERANCE


def test_no_overlaps_and_full_coverage() -> None:
    script = script_from(
        utterance("u1", "One.", 1.0, 3.5),
        utterance("u2", "Two is a longer sentence on the platform.", 3.5, 7.0),
        utterance("u3", "Three.", 7.4, 10.0),
    )
    beats = segment_script(script, PROFILE)
    assert beats[0].start == 1.0
    assert abs(beats[-1].end - 10.0) <= 1e-3
    for prev, curr in zip(beats, beats[1:], strict=False):
        assert curr.start >= prev.end - TIMING_TOLERANCE


def test_segmentation_is_deterministic() -> None:
    script = script_from(
        utterance(
            "u1",
            "A long walk through the city continued for many extra seconds "
            "without punctuation marks here",
            0.0,
            9.5,
        )
    )
    a = segment_script(script, PROFILE)
    b = segment_script(script, PROFILE)
    assert [(x.start, x.end, x.text) for x in a] == [(x.start, x.end, x.text) for x in b]
