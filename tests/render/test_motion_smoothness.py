from __future__ import annotations

import subprocess
from pathlib import Path

from docprod.models.enums import VisualEffect
from docprod.render.effects import effect_params, motion_filter
from docprod.render.ffmpeg import ffmpeg_path, run_ffmpeg

_GRID = (
    "rgbtestsrc=s={w}x{h}:r={fps}:d={d:.4f},"
    "drawgrid=w=iw/16:h=ih/9:t=4:c=white@0.85"
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
    out_dir.mkdir()
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


def test_zoompan_push_in_does_not_hold_frames(tmp_path: Path) -> None:
    width, height, fps, frames, oversample = 320, 180, 30, 45, 4
    duration = frames / fps
    params = effect_params(
        VisualEffect.slow_push_in,
        seed=1,
        scene_id="grid",
        renderer_version="1.1",
    )
    canvas_w, canvas_h = width * oversample, height * oversample
    graph = (
        _GRID.format(w=canvas_w, h=canvas_h, d=duration + 0.2, fps=fps)
        + ","
        + motion_filter(
            params,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            frame_count=frames,
            oversample=oversample,
        )
    )
    pngs = _render_pngs(tmp_path, graph, frames)
    rgb = _rgb_frames(pngs, frames, width, height)
    holds = _identical_pairs(rgb)
    assert holds == 0, f"smooth zoom must change every frame, got {holds} holds"


def test_zoompan_pan_left_does_not_hold_frames(tmp_path: Path) -> None:
    width, height, fps, frames, oversample = 640, 360, 30, 30, 4
    duration = frames / fps
    params = effect_params(
        VisualEffect.pan_left,
        seed=1,
        scene_id="grid",
        renderer_version="1.1",
    )
    canvas_w, canvas_h = width * oversample, height * oversample
    graph = (
        _GRID.format(w=canvas_w, h=canvas_h, d=duration + 0.2, fps=fps)
        + ","
        + motion_filter(
            params,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            frame_count=frames,
            oversample=oversample,
        )
    )
    pngs = _render_pngs(tmp_path, graph, frames)
    rgb = _rgb_frames(pngs, frames, width, height)
    holds = _identical_pairs(rgb)
    assert holds == 0, f"smooth pan must change every frame, got {holds} holds"
