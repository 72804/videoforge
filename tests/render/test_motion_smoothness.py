from __future__ import annotations

import subprocess
from pathlib import Path

from docprod.models.enums import VisualEffect
from docprod.render.effects import effect_params, motion_filter
from docprod.render.ffmpeg import ffmpeg_path, run_ffmpeg
from docprod.render.motion_audit import (
    MotionStatus,
    classify_motion,
    collect_ydif,
    continuity_metrics,
)

_GRID = (
    "rgbtestsrc=s={w}x{h}:r={fps}:d={d:.4f},"
    "drawgrid=w=iw/16:h=ih/9:t=4:c=white@0.85"
)


def _legacy_zoompan_handheld(*, width: int, height: int, fps: int, frames: int) -> str:
    del frames
    return (
        f"zoompan=z='1.05':"
        f"x='(iw-iw/zoom)*0.5+6*sin(2*PI*(on/{fps}*0.28))':"
        f"y='(ih-ih/zoom)*0.5+6*cos(2*PI*(on/{fps}*0.28))':"
        f"d=1:s={width}x{height}:fps={fps}"
    )


def _legacy_integer_zoom_filter(
    *,
    z0: float,
    z1: float,
    duration: float,
    width: int,
    height: int,
) -> str:
    z_expr = f"({z0}+({z1}-{z0})*t/{duration})"
    return (
        f"scale=w='max({width},trunc({width}*{z_expr}/2)*2)':"
        f"h='max({height},trunc({height}*{z_expr}/2)*2)':eval=frame,"
        f"crop={width}:{height}:x='(in_w-{width})/2':y='(in_h-{height})/2'"
    )


def _rgb_frames(png_dir: Path, count: int, width: int, height: int) -> list[bytes]:
    frames: list[bytes] = []
    expected = width * height * 3
    for index in range(1, count + 1):
        png = png_dir / f"f_{index:03d}.png"
        completed = subprocess.run(
            [
                ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(png),
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            check=False,
            capture_output=True,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
        assert len(completed.stdout) == expected
        frames.append(completed.stdout)
    return frames


def _identical_pairs(frames: list[bytes]) -> int:
    return sum(1 for prev, current in zip(frames, frames[1:], strict=False) if prev == current)


def _render_pngs(tmp_path: Path, lavfi: str, frames: int) -> Path:
    out_dir = tmp_path / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            lavfi,
            "-frames:v",
            str(frames),
            str(out_dir / "f_%03d.png"),
        ],
        timeout=60,
    )
    return out_dir


def _render_mp4(tmp_path: Path, lavfi: str, frames: int, name: str = "clip.mp4") -> Path:
    dest = tmp_path / name
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            lavfi,
            "-frames:v",
            str(frames),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            str(dest),
        ],
        timeout=60,
    )
    return dest


def _moving_graph(effect: VisualEffect, width: int, height: int, fps: int, frames: int) -> str:
    duration = frames / fps
    params = effect_params(
        effect,
        seed=1,
        scene_id="grid",
        renderer_version="1.2",
    )
    return (
        _GRID.format(w=width, h=height, d=duration + 0.2, fps=fps)
        + ","
        + motion_filter(
            params,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            frame_count=frames,
            oversample=1,
        )
    )


def test_legacy_integer_zoom_holds_frames(tmp_path: Path) -> None:
    width, height, fps, frames = 320, 180, 30, 45
    duration = frames / fps
    graph = (
        _GRID.format(w=width, h=height, d=duration + 0.2, fps=fps)
        + ","
        + _legacy_integer_zoom_filter(
            z0=1.00, z1=1.05, duration=duration, width=width, height=height
        )
    )
    pngs = _render_pngs(tmp_path, graph, frames)
    rgb = _rgb_frames(pngs, frames, width, height)
    holds = _identical_pairs(rgb)
    assert holds >= 8, f"legacy staircase should hold frames, got {holds} holds"


def test_perspective_push_in_does_not_hold_frames(tmp_path: Path) -> None:
    width, height, fps, frames = 320, 180, 30, 45
    graph = _moving_graph(VisualEffect.slow_push_in, width, height, fps, frames)
    pngs = _render_pngs(tmp_path, graph, frames)
    rgb = _rgb_frames(pngs, frames, width, height)
    assert _identical_pairs(rgb) <= 1
    mp4 = _render_mp4(tmp_path, graph, frames, "push.mp4")
    status, note = classify_motion(
        rendered=VisualEffect.slow_push_in,
        metrics=continuity_metrics(collect_ydif(mp4), frame_count=frames),
        moving=True,
    )
    assert status is MotionStatus.SMOOTH, note


def test_perspective_pan_left_does_not_hold_frames(tmp_path: Path) -> None:
    width, height, fps, frames = 640, 360, 30, 30
    graph = _moving_graph(VisualEffect.pan_left, width, height, fps, frames)
    pngs = _render_pngs(tmp_path, graph, frames)
    rgb = _rgb_frames(pngs, frames, width, height)
    assert _identical_pairs(rgb) <= 1
    mp4 = _render_mp4(tmp_path, graph, frames, "pan.mp4")
    status, note = classify_motion(
        rendered=VisualEffect.pan_left,
        metrics=continuity_metrics(collect_ydif(mp4), frame_count=frames),
        moving=True,
    )
    assert status is MotionStatus.SMOOTH, note


def test_perspective_pull_out_and_surveillance_progress(tmp_path: Path) -> None:
    width, height, fps, frames = 320, 180, 30, 36
    for effect in (VisualEffect.slow_pull_out, VisualEffect.surveillance_zoom):
        graph = _moving_graph(effect, width, height, fps, frames)
        pngs = _render_pngs(tmp_path / effect.value, graph, frames)
        rgb = _rgb_frames(pngs, frames, width, height)
        assert _identical_pairs(rgb) <= 1, effect.value
        mp4 = _render_mp4(tmp_path / effect.value, graph, frames, f"{effect.value}.mp4")
        status, note = classify_motion(
            rendered=effect,
            metrics=continuity_metrics(collect_ydif(mp4), frame_count=frames),
            moving=True,
        )
        assert status is MotionStatus.SMOOTH, f"{effect.value} {note}"


def test_legacy_zoompan_handheld_fails_continuity(tmp_path: Path) -> None:
    width, height, fps, frames = 320, 180, 30, 48
    duration = frames / fps
    graph = (
        _GRID.format(w=width, h=height, d=duration + 0.2, fps=fps)
        + ","
        + _legacy_zoompan_handheld(width=width, height=height, fps=fps, frames=frames)
    )
    mp4 = _render_mp4(tmp_path, graph, frames, "legacy.mp4")
    metrics = continuity_metrics(collect_ydif(mp4), frame_count=frames)
    status, _note = classify_motion(
        rendered=VisualEffect.documentary_handheld,
        metrics=metrics,
        moving=True,
    )
    assert status is MotionStatus.FAIL


def test_perspective_handheld_passes_continuity(tmp_path: Path) -> None:
    width, height, fps, frames = 320, 180, 30, 48
    graph = _moving_graph(VisualEffect.documentary_handheld, width, height, fps, frames)
    mp4 = _render_mp4(tmp_path, graph, frames, "handheld.mp4")
    pngs = _render_pngs(tmp_path / "png", graph, frames)
    rgb = _rgb_frames(pngs, frames, width, height)
    assert _identical_pairs(rgb) == 0
    metrics = continuity_metrics(collect_ydif(mp4), frame_count=frames)
    status, note = classify_motion(
        rendered=VisualEffect.documentary_handheld,
        metrics=metrics,
        moving=True,
    )
    assert status is MotionStatus.SMOOTH, note
    assert metrics.longest_hold < 4
