from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from docprod.audio.models import AlignedToken, AlignmentReport
from docprod.cli import app
from docprod.quality.driving_package import (
    BLOCK_DELTA_S,
    evaluate_sync,
    find_dialogue_span,
    validate_driving_video,
)
from docprod.render.ffmpeg import run_ffmpeg

runner = CliRunner()


def _alignment() -> AlignmentReport:
    words = [
        ("Bir", 39.56, 39.84),
        ("kola", 39.84, 40.12),
        ("aldı", 40.12, 40.34),
        ("Kemal", 40.98, 41.20),
        ("e", 41.20, 41.38),
        ("yaz", 41.38, 41.58),
        ("Bakkal", 42.40, 42.60),
    ]
    tokens = [
        AlignedToken(
            text=text,
            scene_id="scene_0009",
            start=start,
            end=end,
            status="matched",
            timing_source="whisper",
        )
        for text, start, end in words
    ]
    return AlignmentReport(
        project_id="tiny",
        canonical_word_count=len(tokens),
        matched_word_count=len(tokens),
        interpolated_word_count=0,
        unmatched_word_count=0,
        match_fraction=1.0,
        tokens=tokens,
        quality_passed=True,
    )


def test_find_b07_line_from_alignment() -> None:
    span = find_dialogue_span(_alignment(), scene_id="scene_0009", beat_id="b07")
    assert span.master_start == 40.98
    assert span.master_end == 41.58
    assert span.speech_duration == 0.6
    assert span.extract_start == 39.48
    assert span.extract_end == 43.58
    assert span.line_rel_start == 1.5
    assert span.line_rel_end == 2.1


def test_sync_thresholds() -> None:
    ok = evaluate_sync(
        expected_onset=4.5,
        expected_end=5.1,
        measured_onset=4.55,
        measured_end=5.16,
    )
    assert ok.status == "ok"
    warn = evaluate_sync(
        expected_onset=4.5,
        expected_end=5.1,
        measured_onset=4.65,
        measured_end=5.1,
    )
    assert warn.status == "warn"
    blocked = evaluate_sync(
        expected_onset=4.5,
        expected_end=5.1,
        measured_onset=4.5 + BLOCK_DELTA_S + 0.01,
        measured_end=5.1 + BLOCK_DELTA_S + 0.01,
    )
    assert blocked.status == "block"


def test_validate_driving_video_local(tmp_path: Path) -> None:
    dest = tmp_path / "take.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:r=24:d=8",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=8",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(dest),
        ],
        timeout=60,
    )
    check = validate_driving_video(dest)
    assert check.ok
    assert check.decodable
    assert check.has_audio
    assert check.width == 1280
    assert check.height == 720
    result = runner.invoke(app, ["validate-driving-video", str(dest), "--no-sync"])
    assert result.exit_code == 0, result.output
    assert "paid_calls=0" in result.output
    assert "1280x720" in result.output
