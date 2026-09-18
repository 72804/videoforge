from __future__ import annotations

import math
import re
import statistics
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from docprod.models.enums import VisualEffect
from docprod.render.effects import camera_motion_needed, effect_params
from docprod.render.ffmpeg import FFmpegError, ffmpeg_path
from docprod.render.models import SegmentRecord

NEAR_STATIC_YDIF = 0.2
FAIL_HOLD_RUN = 4
REVIEW_HOLD_RUN = 3
FAIL_NEAR_STATIC_FRACTION = 0.30
REVIEW_NEAR_STATIC_FRACTION = 0.18
SPIKE_RATIO_FAIL = 40.0

_YDIF_RE = re.compile(r"lavfi\.signalstats\.YDIF=([0-9.eE+-]+)")


class MotionStatus(StrEnum):
    STATIC_EXPECTED = "STATIC_EXPECTED"
    SMOOTH = "SMOOTH"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


@dataclass(frozen=True)
class ContinuityMetrics:
    frame_count: int
    ydif_count: int
    near_static_count: int
    longest_hold: int
    median_ydif: float
    p10_ydif: float
    p90_ydif: float
    max_ydif: float
    min_ydif: float
    max_median_ratio: float
    spike_count: int
    exact_duplicate_pairs: int


@dataclass(frozen=True)
class MotionAuditRow:
    scene_id: str
    effect_requested: VisualEffect
    effect_rendered: VisualEffect
    frames: int
    near_static: int
    longest_hold: int
    median_ydif: float
    p90_ydif: float
    max_ydif: float
    status: MotionStatus
    note: str = ""


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    index = min(len(sorted_vals) - 1, max(0, round((len(sorted_vals) - 1) * p)))
    return sorted_vals[index]


def collect_ydif(path: Path) -> list[float]:
    completed = subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            "signalstats,metadata=print:file=-",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FFmpegError(
            f"signalstats failed for {path}: {completed.stderr.strip()[-1500:]}"
        )
    values: list[float] = []
    for line in (completed.stdout or "").splitlines():
        match = _YDIF_RE.search(line)
        if match:
            values.append(float(match.group(1)))
    return values


def _longest_run(flags: list[bool]) -> int:
    longest = current = 0
    for flag in flags:
        if flag:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def continuity_metrics(ydif: list[float], *, frame_count: int | None = None) -> ContinuityMetrics:
    if not ydif:
        return ContinuityMetrics(
            frame_count=frame_count or 0,
            ydif_count=0,
            near_static_count=0,
            longest_hold=0,
            median_ydif=0.0,
            p10_ydif=0.0,
            p90_ydif=0.0,
            max_ydif=0.0,
            min_ydif=0.0,
            max_median_ratio=0.0,
            spike_count=0,
            exact_duplicate_pairs=0,
        )
    ordered = sorted(ydif)
    median = statistics.median(ydif)
    near_flags = [value < NEAR_STATIC_YDIF for value in ydif]
    max_v = max(ydif)
    ratio = (max_v / median) if median > 1e-9 else (math.inf if max_v else 0.0)
    spike_cut = max(NEAR_STATIC_YDIF * 8, median * 8)
    spike = sum(1 for value in ydif if median > 1e-9 and value > spike_cut)
    return ContinuityMetrics(
        frame_count=frame_count if frame_count is not None else len(ydif),
        ydif_count=len(ydif),
        near_static_count=sum(near_flags),
        longest_hold=_longest_run(near_flags),
        median_ydif=float(median),
        p10_ydif=_percentile(ordered, 0.10),
        p90_ydif=_percentile(ordered, 0.90),
        max_ydif=max_v,
        min_ydif=min(ydif),
        max_median_ratio=float(ratio) if math.isfinite(ratio) else 999.0,
        spike_count=spike,
        exact_duplicate_pairs=sum(1 for value in ydif if value == 0.0),
    )


def classify_motion(
    *,
    rendered: VisualEffect,
    metrics: ContinuityMetrics,
    moving: bool,
) -> tuple[MotionStatus, str]:
    if not moving or rendered is VisualEffect.none:
        return MotionStatus.STATIC_EXPECTED, "no camera transform"
    diffs = max(1, metrics.ydif_count)
    hold_frac = metrics.near_static_count / diffs
    if metrics.longest_hold >= FAIL_HOLD_RUN or hold_frac >= FAIL_NEAR_STATIC_FRACTION:
        return (
            MotionStatus.FAIL,
            f"hold_run={metrics.longest_hold} near_static={hold_frac:.2f}",
        )
    if metrics.max_median_ratio >= SPIKE_RATIO_FAIL and metrics.spike_count >= 3:
        return (
            MotionStatus.FAIL,
            f"spike_ratio={metrics.max_median_ratio:.1f} spikes={metrics.spike_count}",
        )
    if metrics.longest_hold >= REVIEW_HOLD_RUN or hold_frac >= REVIEW_NEAR_STATIC_FRACTION:
        return (
            MotionStatus.REVIEW,
            f"hold_run={metrics.longest_hold} near_static={hold_frac:.2f}",
        )
    return MotionStatus.SMOOTH, ""


def audit_segment_file(
    path: Path,
    *,
    scene_id: str,
    requested: VisualEffect,
    rendered: VisualEffect,
    seed: int,
    renderer_version: str,
    frame_count: int | None = None,
) -> MotionAuditRow:
    params = effect_params(
        requested,
        seed=seed,
        scene_id=scene_id,
        renderer_version=renderer_version,
    )
    ydif = collect_ydif(path)
    metrics = continuity_metrics(ydif, frame_count=frame_count)
    status, note = classify_motion(
        rendered=rendered,
        metrics=metrics,
        moving=camera_motion_needed(params),
    )
    return MotionAuditRow(
        scene_id=scene_id,
        effect_requested=requested,
        effect_rendered=rendered,
        frames=metrics.frame_count,
        near_static=metrics.near_static_count,
        longest_hold=metrics.longest_hold,
        median_ydif=metrics.median_ydif,
        p90_ydif=metrics.p90_ydif,
        max_ydif=metrics.max_ydif,
        status=status,
        note=note,
    )


def audit_records(
    segments_dir: Path,
    records: list[SegmentRecord],
    *,
    seed: int,
    renderer_version: str,
) -> list[MotionAuditRow]:
    rows: list[MotionAuditRow] = []
    for record in records:
        path = segments_dir / f"{record.scene_id}.mp4"
        if not path.is_file():
            rows.append(
                MotionAuditRow(
                    scene_id=record.scene_id,
                    effect_requested=record.effect_requested,
                    effect_rendered=record.effect_rendered,
                    frames=record.frame_count,
                    near_static=0,
                    longest_hold=0,
                    median_ydif=0.0,
                    p90_ydif=0.0,
                    max_ydif=0.0,
                    status=MotionStatus.FAIL,
                    note="missing segment file",
                )
            )
            continue
        rows.append(
            audit_segment_file(
                path,
                scene_id=record.scene_id,
                requested=record.effect_requested,
                rendered=record.effect_rendered,
                seed=seed,
                renderer_version=renderer_version,
                frame_count=record.frame_count,
            )
        )
    return rows
