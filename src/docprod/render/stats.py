from __future__ import annotations

from docprod.render.ffmpeg import ProbeInfo


def frame_count_for_span(start: float, end: float, fps: int) -> int:
    start_f = round(start * fps)
    end_f = round(end * fps)
    return max(1, end_f - start_f)


def duration_tolerance(fps: int) -> float:
    """Single final AAC mux + 1 frame. Does not accumulate per scene."""
    return (1.0 / fps) + 0.12


def duration_ok(expected: float, actual: float, fps: int) -> bool:
    return abs(actual - expected) <= duration_tolerance(fps)


def probe_looks_valid(probe: ProbeInfo, *, width: int, height: int, fps: int) -> bool:
    if not probe.has_video or probe.width != width or probe.height != height:
        return False
    if probe.video_codec not in {"h264", "libx264", "avc1"} and probe.video_codec is None:
        return False
    return True
