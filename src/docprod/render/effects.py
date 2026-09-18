from __future__ import annotations

import math
import random
from dataclasses import dataclass

from docprod.models.enums import VisualEffect

# Requested effect -> implemented preview effect. Identity means native impl.
EFFECT_IMPLEMENTATION: dict[VisualEffect, VisualEffect] = {
    VisualEffect.none: VisualEffect.none,
    VisualEffect.slow_push_in: VisualEffect.slow_push_in,
    VisualEffect.slow_pull_out: VisualEffect.slow_pull_out,
    VisualEffect.pan_left: VisualEffect.pan_left,
    VisualEffect.pan_right: VisualEffect.pan_right,
    VisualEffect.documentary_handheld: VisualEffect.documentary_handheld,
    VisualEffect.surveillance_zoom: VisualEffect.surveillance_zoom,
    VisualEffect.cctv_treatment: VisualEffect.cctv_treatment,
    VisualEffect.police_light_flicker: VisualEffect.police_light_flicker,
    VisualEffect.parallax_2_5d: VisualEffect.slow_push_in,
    VisualEffect.photo_table: VisualEffect.slow_push_in,
    VisualEffect.evidence_board: VisualEffect.slow_push_in,
    VisualEffect.newspaper_reveal: VisualEffect.slow_push_in,
    VisualEffect.map_route: VisualEffect.pan_left,
    VisualEffect.silhouette_reveal: VisualEffect.slow_push_in,
    VisualEffect.circle_highlight: VisualEffect.slow_push_in,
    VisualEffect.arrow_annotation: VisualEffect.slow_push_in,
    VisualEffect.location_date_card: VisualEffect.none,
}

# Output-resolution zoom range. Applied on an oversampled canvas via zoompan.
PUSH_IN_SCALE = (1.00, 1.05)
PULL_OUT_SCALE = (1.05, 1.00)


@dataclass(frozen=True)
class EffectParams:
    requested: VisualEffect
    rendered: VisualEffect
    fallback: bool
    scale_start: float
    scale_end: float
    pan_x0: float
    pan_x1: float
    pan_y0: float
    pan_y1: float
    handheld_amp: float
    handheld_freq: float
    handheld_phase: float
    flicker: bool
    desaturate: bool


@dataclass(frozen=True)
class MotionSample:
    frame_index: int
    progress: float
    scale: float
    pan_x: float
    pan_y: float
    offset_x: float
    offset_y: float


def resolve_effect(requested: VisualEffect) -> tuple[VisualEffect, bool]:
    rendered = EFFECT_IMPLEMENTATION[requested]
    return rendered, rendered is not requested


def effect_params(
    requested: VisualEffect,
    *,
    seed: int,
    scene_id: str,
    renderer_version: str,
) -> EffectParams:
    rendered, fallback = resolve_effect(requested)
    rng = random.Random(f"{seed}:{scene_id}:{renderer_version}:{rendered.value}")
    pan_x0, pan_x1 = 0.5, 0.5
    pan_y0, pan_y1 = 0.5, 0.5
    scale_start, scale_end = 1.0, 1.0
    amp, freq, phase = 0.0, 0.0, 0.0
    flicker = False
    desaturate = False
    if rendered is VisualEffect.slow_push_in:
        scale_start, scale_end = PUSH_IN_SCALE
    elif rendered is VisualEffect.slow_pull_out:
        scale_start, scale_end = PULL_OUT_SCALE
    elif rendered is VisualEffect.pan_left:
        scale_start = scale_end = 1.08
        pan_x0, pan_x1 = 0.85, 0.15
    elif rendered is VisualEffect.pan_right:
        scale_start = scale_end = 1.08
        pan_x0, pan_x1 = 0.15, 0.85
    elif rendered is VisualEffect.documentary_handheld:
        scale_start = scale_end = 1.05
        amp = 6.0
        freq = 0.28
        phase = rng.random()
    elif rendered is VisualEffect.surveillance_zoom:
        scale_start, scale_end = 1.04, 1.14
        pan_x0 = pan_x1 = 0.42 + rng.random() * 0.16
        pan_y0 = pan_y1 = 0.42 + rng.random() * 0.16
    elif rendered is VisualEffect.cctv_treatment:
        scale_start, scale_end = 1.04, 1.12
        desaturate = True
    elif rendered is VisualEffect.police_light_flicker:
        scale_start = scale_end = 1.04
        amp = 3.0
        freq = 0.22
        phase = rng.random()
        flicker = True
    return EffectParams(
        requested=requested,
        rendered=rendered,
        fallback=fallback,
        scale_start=scale_start,
        scale_end=scale_end,
        pan_x0=pan_x0,
        pan_x1=pan_x1,
        pan_y0=pan_y0,
        pan_y1=pan_y1,
        handheld_amp=amp,
        handheld_freq=freq,
        handheld_phase=phase,
        flicker=flicker,
        desaturate=desaturate,
    )


def motion_progress(frame_index: int, frame_count: int) -> float:
    """Normalized linear progress p in [0, 1] for camera moves."""
    if frame_count <= 1:
        return 0.0
    return frame_index / (frame_count - 1)


def sample_motion(
    params: EffectParams,
    *,
    frame_index: int,
    frame_count: int,
    fps: int,
) -> MotionSample:
    """Deterministic per-frame camera state. Independent of FFmpeg."""
    progress = motion_progress(frame_index, frame_count)
    scale = params.scale_start + (params.scale_end - params.scale_start) * progress
    pan_x = params.pan_x0 + (params.pan_x1 - params.pan_x0) * progress
    pan_y = params.pan_y0 + (params.pan_y1 - params.pan_y0) * progress
    t = frame_index / max(fps, 1)
    angle = 2 * math.pi * (t * params.handheld_freq + params.handheld_phase)
    offset_x = params.handheld_amp * math.sin(angle)
    offset_y = params.handheld_amp * math.cos(angle)
    return MotionSample(
        frame_index=frame_index,
        progress=progress,
        scale=scale,
        pan_x=pan_x,
        pan_y=pan_y,
        offset_x=offset_x,
        offset_y=offset_y,
    )


def camera_motion_needed(params: EffectParams) -> bool:
    return (
        abs(params.scale_end - params.scale_start) > 1e-9
        or abs(params.pan_x1 - params.pan_x0) > 1e-9
        or abs(params.pan_y1 - params.pan_y0) > 1e-9
        or params.handheld_amp > 0
    )


def oversampled_size(width: int, height: int, factor: int) -> tuple[int, int]:
    factor = max(1, factor)
    canvas_w = width * factor
    canvas_h = height * factor
    if canvas_w % 2:
        canvas_w += 1
    if canvas_h % 2:
        canvas_h += 1
    return canvas_w, canvas_h


def legacy_integer_scale_width(scale: float, output_width: int) -> int:
    """Old even-pixel scale width. Kept to document the staircase defect."""
    return max(output_width, int(output_width * scale / 2) * 2)


def motion_filter(
    params: EffectParams,
    *,
    duration: float,
    width: int,
    height: int,
    fps: int,
    frame_count: int,
    oversample: int = 4,
) -> str:
    """Oversampled zoompan + Lanczos downsample. `width`/`height` are OUTPUT pixels."""
    del duration  # progress is frame-linear, not wall-clock eased
    filters: list[str] = []
    canvas_w, canvas_h = oversampled_size(width, height, oversample)
    if camera_motion_needed(params):
        denom = max(1, frame_count - 1)
        p_expr = f"min(1\\,on/{denom})"
        z0 = params.scale_start
        z1 = params.scale_end
        z_expr = f"({z0}+({z1}-{z0})*{p_expr})"
        amp = params.handheld_amp * oversample
        hx = (
            f"+{amp}*sin(2*PI*(on/{max(fps, 1)}*{params.handheld_freq}"
            f"+{params.handheld_phase}))"
            if amp
            else ""
        )
        hy = (
            f"+{amp}*cos(2*PI*(on/{max(fps, 1)}*{params.handheld_freq}"
            f"+{params.handheld_phase}))"
            if amp
            else ""
        )
        x_expr = (
            f"(iw-iw/zoom)*({params.pan_x0}+({params.pan_x1}-{params.pan_x0})*{p_expr}){hx}"
        )
        y_expr = (
            f"(ih-ih/zoom)*({params.pan_y0}+({params.pan_y1}-{params.pan_y0})*{p_expr}){hy}"
        )
        x_clamped = f"max(0\\,min((iw-iw/zoom)\\,{x_expr}))"
        y_clamped = f"max(0\\,min((ih-ih/zoom)\\,{y_expr}))"
        filters.append(
            f"zoompan=z='{z_expr}':x='{x_clamped}':y='{y_clamped}':"
            f"d=1:s={canvas_w}x{canvas_h}:fps={fps}"
        )
    if canvas_w != width or canvas_h != height:
        filters.append(f"scale={width}:{height}:flags=lanczos")
    if params.desaturate:
        filters.append("eq=saturation=0.35:contrast=1.08")
    if params.flicker:
        filters.append("eq=brightness='0.035*sin(2*PI*t*1.6)'")
    if not filters:
        return "null"
    return ",".join(filters)
