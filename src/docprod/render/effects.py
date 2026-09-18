from __future__ import annotations

import math
import random
from dataclasses import dataclass

from docprod.models.enums import VisualEffect

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
    VisualEffect.photo_table: VisualEffect.photo_table,
    VisualEffect.evidence_board: VisualEffect.evidence_board,
    VisualEffect.newspaper_reveal: VisualEffect.newspaper_reveal,
    VisualEffect.map_route: VisualEffect.map_route,
    VisualEffect.silhouette_reveal: VisualEffect.slow_push_in,
    VisualEffect.circle_highlight: VisualEffect.slow_push_in,
    VisualEffect.arrow_annotation: VisualEffect.slow_push_in,
    VisualEffect.location_date_card: VisualEffect.none,
}

PUSH_IN_SCALE = (1.00, 1.05)
PULL_OUT_SCALE = (1.05, 1.00)
PAN_SCALE = 1.08
HANDHELD_SCALE = 1.02
SURVEILLANCE_SCALE = (1.04, 1.14)


@dataclass(frozen=True)
class Oscillator:
    amp: float
    freq: float
    phase: float


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
    x_oscs: tuple[Oscillator, ...]
    y_oscs: tuple[Oscillator, ...]
    flicker: bool
    desaturate: bool


@dataclass(frozen=True)
class CameraPose:
    """Floating-point camera state for one frame. Independent of FFmpeg."""

    frame_index: int
    progress: float
    scale: float
    center_x: float
    center_y: float
    left: float
    top: float
    right: float
    bottom: float


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
    x_oscs: tuple[Oscillator, ...] = ()
    y_oscs: tuple[Oscillator, ...] = ()
    flicker = False
    desaturate = False
    if rendered is VisualEffect.slow_push_in:
        scale_start, scale_end = PUSH_IN_SCALE
    elif rendered is VisualEffect.slow_pull_out:
        scale_start, scale_end = PULL_OUT_SCALE
    elif rendered is VisualEffect.pan_left:
        scale_start = scale_end = PAN_SCALE
        pan_x0, pan_x1 = 0.85, 0.15
    elif rendered is VisualEffect.pan_right:
        scale_start = scale_end = PAN_SCALE
        pan_x0, pan_x1 = 0.15, 0.85
    elif rendered is VisualEffect.documentary_handheld:
        scale_start = scale_end = HANDHELD_SCALE
        x_oscs = (
            Oscillator(amp=3.2, freq=0.23, phase=rng.random()),
            Oscillator(amp=1.1, freq=0.47, phase=rng.random()),
        )
        y_oscs = (
            Oscillator(amp=2.4, freq=0.19, phase=rng.random()),
            Oscillator(amp=0.8, freq=0.41, phase=rng.random()),
        )
    elif rendered is VisualEffect.surveillance_zoom:
        scale_start, scale_end = SURVEILLANCE_SCALE
        pan_x0 = pan_x1 = 0.42 + rng.random() * 0.16
        pan_y0 = pan_y1 = 0.42 + rng.random() * 0.16
    elif rendered is VisualEffect.cctv_treatment:
        scale_start, scale_end = 1.04, 1.12
        desaturate = True
    elif rendered is VisualEffect.police_light_flicker:
        scale_start = scale_end = HANDHELD_SCALE
        x_oscs = (Oscillator(amp=1.6, freq=0.22, phase=rng.random()),)
        y_oscs = (Oscillator(amp=1.2, freq=0.18, phase=rng.random()),)
        flicker = True
    elif rendered is VisualEffect.photo_table:
        scale_start, scale_end = 1.03, 1.08
        pan_x0, pan_x1 = 0.48, 0.54
        pan_y0, pan_y1 = 0.58, 0.46
    elif rendered is VisualEffect.newspaper_reveal:
        scale_start, scale_end = 1.16, 1.05
        pan_y0, pan_y1 = 0.42, 0.52
    elif rendered is VisualEffect.evidence_board:
        scale_start = scale_end = 1.12
        pan_x0, pan_x1 = 0.32, 0.68
        pan_y0, pan_y1 = 0.46, 0.54
    elif rendered is VisualEffect.map_route:
        scale_start, scale_end = 1.00, 1.035
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
        x_oscs=x_oscs,
        y_oscs=y_oscs,
        flicker=flicker,
        desaturate=desaturate,
    )


def motion_progress(frame_index: int, frame_count: int) -> float:
    if frame_count <= 1:
        return 0.0
    return frame_index / (frame_count - 1)


def _osc_sum(oscs: tuple[Oscillator, ...], t: float) -> float:
    total = 0.0
    for osc in oscs:
        total += osc.amp * math.sin(2 * math.pi * (t * osc.freq + osc.phase))
    return total


def sample_camera(
    params: EffectParams,
    *,
    frame_index: int,
    frame_count: int,
    fps: int,
    width: int,
    height: int,
) -> CameraPose:
    progress = motion_progress(frame_index, frame_count)
    scale = params.scale_start + (params.scale_end - params.scale_start) * progress
    scale = max(scale, 1.0)
    pan_x = params.pan_x0 + (params.pan_x1 - params.pan_x0) * progress
    pan_y = params.pan_y0 + (params.pan_y1 - params.pan_y0) * progress
    t = frame_index / max(fps, 1)
    sample_w = width / scale
    sample_h = height / scale
    center_x = sample_w / 2 + pan_x * (width - sample_w) + _osc_sum(params.x_oscs, t)
    center_y = sample_h / 2 + pan_y * (height - sample_h) + _osc_sum(params.y_oscs, t)
    half_w = sample_w / 2
    half_h = sample_h / 2
    center_x = min(max(center_x, half_w), width - half_w)
    center_y = min(max(center_y, half_h), height - half_h)
    return CameraPose(
        frame_index=frame_index,
        progress=progress,
        scale=scale,
        center_x=center_x,
        center_y=center_y,
        left=center_x - half_w,
        top=center_y - half_h,
        right=center_x + half_w,
        bottom=center_y + half_h,
    )


def sample_motion(
    params: EffectParams,
    *,
    frame_index: int,
    frame_count: int,
    fps: int,
    width: int = 1280,
    height: int = 720,
) -> CameraPose:
    return sample_camera(
        params,
        frame_index=frame_index,
        frame_count=frame_count,
        fps=fps,
        width=width,
        height=height,
    )


def camera_motion_needed(params: EffectParams) -> bool:
    return (
        abs(params.scale_end - params.scale_start) > 1e-9
        or abs(params.pan_x1 - params.pan_x0) > 1e-9
        or abs(params.pan_y1 - params.pan_y0) > 1e-9
        or any(osc.amp for osc in params.x_oscs)
        or any(osc.amp for osc in params.y_oscs)
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
    return max(output_width, int(output_width * scale / 2) * 2)


def _osc_expr(oscs: tuple[Oscillator, ...], *, fps: int, oversample: int) -> str:
    if not oscs:
        return "0"
    parts: list[str] = []
    for osc in oscs:
        amp = osc.amp * oversample
        parts.append(
            f"({amp}*sin(2*PI*((in-1)/{max(fps, 1)}*{osc.freq}+{osc.phase})))"
        )
    return "+".join(parts)


def motion_filter(
    params: EffectParams,
    *,
    duration: float,
    width: int,
    height: int,
    fps: int,
    frame_count: int,
    oversample: int = 1,
) -> str:
    """Fractional perspective camera. `width`/`height` are OUTPUT pixels."""
    del duration
    filters: list[str] = []
    canvas_w, canvas_h = oversampled_size(width, height, oversample)
    if camera_motion_needed(params):
        denom = max(1, frame_count - 1)
        p_expr = f"min(1\\,max(0\\,(in-1)/{denom}))"
        z0 = params.scale_start
        z1 = params.scale_end
        z_expr = f"({z0}+({z1}-{z0})*{p_expr})"
        hx = _osc_expr(params.x_oscs, fps=fps, oversample=oversample)
        hy = _osc_expr(params.y_oscs, fps=fps, oversample=oversample)
        cx = (
            f"(W/({z_expr}))/2+"
            f"({params.pan_x0}+({params.pan_x1}-{params.pan_x0})*{p_expr})"
            f"*(W-W/({z_expr}))+({hx})"
        )
        cy = (
            f"(H/({z_expr}))/2+"
            f"({params.pan_y0}+({params.pan_y1}-{params.pan_y0})*{p_expr})"
            f"*(H-H/({z_expr}))+({hy})"
        )
        left = f"({cx})-(W/(2*({z_expr})))"
        right = f"({cx})+(W/(2*({z_expr})))"
        top = f"({cy})-(H/(2*({z_expr})))"
        bottom = f"({cy})+(H/(2*({z_expr})))"
        filters.append(
            f"perspective="
            f"x0='{left}':y0='{top}':"
            f"x1='{right}':y1='{top}':"
            f"x2='{left}':y2='{bottom}':"
            f"x3='{right}':y3='{bottom}':"
            f"interpolation=cubic:sense=source:eval=frame"
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
