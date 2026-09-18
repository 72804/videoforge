from __future__ import annotations

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
        scale_start, scale_end = 1.02, 1.07
    elif rendered is VisualEffect.slow_pull_out:
        scale_start, scale_end = 1.07, 1.02
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


def motion_filter(params: EffectParams, *, duration: float, width: int, height: int) -> str:
    """Return an ffmpeg filter chain (no leading comma) applying documentary motion."""
    dur = max(duration, 0.001)
    filters: list[str] = []
    needs_motion = (
        abs(params.scale_end - params.scale_start) > 1e-6
        or abs(params.pan_x1 - params.pan_x0) > 1e-6
        or abs(params.pan_y1 - params.pan_y0) > 1e-6
        or params.handheld_amp > 0
    )
    if needs_motion:
        z0 = params.scale_start
        z1 = params.scale_end
        # Animate scale then crop a WxH window. Expressions use t in seconds.
        z_expr = f"({z0}+({z1}-{z0})*t/{dur})"
        filters.append(
            f"scale=w='max({width},trunc({width}*{z_expr}/2)*2)':"
            f"h='max({height},trunc({height}*{z_expr}/2)*2)':eval=frame"
        )
        hx = (
            f"+{params.handheld_amp}*sin(2*PI*(t*{params.handheld_freq}+{params.handheld_phase}))"
            if params.handheld_amp
            else ""
        )
        hy = (
            f"+{params.handheld_amp}*cos(2*PI*(t*{params.handheld_freq}+{params.handheld_phase}))"
            if params.handheld_amp
            else ""
        )
        x_expr = (
            f"(in_w-{width})*({params.pan_x0}+({params.pan_x1}-{params.pan_x0})*t/{dur}){hx}"
        )
        y_expr = (
            f"(in_h-{height})*({params.pan_y0}+({params.pan_y1}-{params.pan_y0})*t/{dur}){hy}"
        )
        filters.append(
            f"crop={width}:{height}:x='max(0,min(in_w-{width},{x_expr}))':"
            f"y='max(0,min(in_h-{height},{y_expr}))'"
        )
    if params.desaturate:
        filters.append("eq=saturation=0.35:contrast=1.08")
    if params.flicker:
        filters.append("eq=brightness='0.035*sin(2*PI*t*1.6)'")
    if not filters:
        return "null"
    return ",".join(filters)
