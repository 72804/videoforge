from __future__ import annotations

import math

from docprod.quality.catalog import get_model

VEO_LITE_BILLABLE = 8.0
KLING25_OPTIONS = (5, 10)
GEN45_MIN = 2
GEN45_MAX = 10
ACT_TWO_MIN = 3
ACT_TWO_MAX = 30


def used_seconds_for_scene(duration: float) -> float:
    return max(0.0, float(duration))


def billable_seconds(model_id: str, used: float) -> float:
    """Smallest documented billable duration that covers `used` seconds."""
    used = max(0.0, float(used))
    spec = get_model(model_id)
    if model_id.startswith("veo-3.1-lite"):
        return VEO_LITE_BILLABLE
    if model_id in {"kling-2.5-turbo-i2v", "kling-3"} or (
        spec is not None and spec.duration_options == KLING25_OPTIONS
    ):
        for option in KLING25_OPTIONS:
            if used <= option + 1e-9:
                return float(option)
        return float(KLING25_OPTIONS[-1])
    if model_id == "runway-gen-4.5":
        if used <= 0:
            return float(GEN45_MIN)
        return float(min(GEN45_MAX, max(GEN45_MIN, math.ceil(used - 1e-9))))
    if model_id == "runway-act-two":
        if used <= 0:
            return float(ACT_TWO_MIN)
        return float(min(ACT_TWO_MAX, max(ACT_TWO_MIN, math.ceil(used - 1e-9))))
    if spec is not None and spec.duration_options:
        for option in spec.duration_options:
            if used <= option + 1e-9:
                return float(option)
        return float(spec.duration_options[-1])
    if spec is not None and spec.min_duration_seconds and spec.max_duration_seconds:
        low = spec.min_duration_seconds
        high = spec.max_duration_seconds
        return float(min(high, max(low, math.ceil(used - 1e-9) if used else low)))
    return used


def wasted_seconds(billable: float, used: float) -> float:
    return round(max(0.0, billable - used), 3)


def cost_per_used_second(cost: float | None, used: float) -> float | None:
    if cost is None or used <= 0:
        return None
    return round(cost / used, 6)


def trim_to_scene_window(clip_duration: float, scene_duration: float) -> float:
    """Keep narration timing: play at most the scene window."""
    if scene_duration <= 0:
        return 0.0
    return round(min(clip_duration, scene_duration), 3)
