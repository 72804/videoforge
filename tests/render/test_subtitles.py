from __future__ import annotations

from docprod.models.scene import ScenePlan
from docprod.render.subtitles import (
    ass_timestamp,
    build_ass,
    build_srt,
    srt_timestamp,
    wrap_caption,
)
from tests.render.helpers import mini_plan, mini_scene


def test_srt_timestamps_and_turkish() -> None:
    plan = mini_plan(
        mini_scene("scene_0001", 0.0, 2.5, subtitle="İstanbul'daki tren istasyonu boştu."),
        mini_scene("scene_0002", 2.5, 4.0, subtitle="ç ğ ı İ ö ş ü"),
    )
    srt = build_srt(plan)
    assert "00:00:00,000 --> 00:00:02,500" in srt
    assert "İstanbul'daki" in srt
    assert "ç ğ ı İ ö ş ü" in srt
    assert srt_timestamp(65.4) == "00:01:05,400"


def test_ass_turkish_and_empty_omitted() -> None:
    plan = mini_plan(
        mini_scene("scene_0001", 0.0, 1.2, subtitle="Mahkeme tutanağı yoktu."),
        mini_scene("scene_0002", 1.2, 2.0, subtitle=""),
    )
    ass = build_ass(plan, play_res_x=1280, play_res_y=720)
    assert "Mahkeme tutanağı yoktu." in ass
    assert ass.count("Dialogue:") == 1
    assert ass_timestamp(1.2).startswith("0:00:01")


def test_subtitle_wrapping() -> None:
    long = " ".join(["kelime"] * 20)
    lines = wrap_caption(long, width=20, max_lines=2)
    assert 1 <= len(lines) <= 2
    assert all(lines)


def test_empty_plan_captions() -> None:
    plan = ScenePlan(project_id="x", scenes=[], total_duration=0)
    assert build_srt(plan) == ""
