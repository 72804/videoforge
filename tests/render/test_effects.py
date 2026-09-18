from __future__ import annotations

from docprod.models.enums import VisualEffect
from docprod.render.effects import (
    EFFECT_IMPLEMENTATION,
    HANDHELD_SCALE,
    PULL_OUT_SCALE,
    PUSH_IN_SCALE,
    effect_params,
    legacy_integer_scale_width,
    motion_filter,
    motion_progress,
    resolve_effect,
    sample_camera,
)


def test_registry_covers_every_visual_effect() -> None:
    for effect in VisualEffect:
        assert effect in EFFECT_IMPLEMENTATION
        rendered, fallback = resolve_effect(effect)
        assert isinstance(rendered, VisualEffect)


def test_deterministic_effect_parameters() -> None:
    a = effect_params(
        VisualEffect.documentary_handheld,
        seed=42,
        scene_id="scene_0004",
        renderer_version="1.2",
    )
    b = effect_params(
        VisualEffect.documentary_handheld,
        seed=42,
        scene_id="scene_0004",
        renderer_version="1.2",
    )
    c = effect_params(
        VisualEffect.documentary_handheld,
        seed=99,
        scene_id="scene_0004",
        renderer_version="1.2",
    )
    assert a == b
    assert a.x_oscs[0].phase != c.x_oscs[0].phase


def test_fallback_mapping_recorded() -> None:
    rendered, fallback = resolve_effect(VisualEffect.parallax_2_5d)
    assert fallback is True
    assert rendered is VisualEffect.slow_push_in
    native, native_fb = resolve_effect(VisualEffect.slow_push_in)
    assert native_fb is False
    assert native is VisualEffect.slow_push_in


def _poses(effect: VisualEffect, *, frames: int = 105, fps: int = 30, width=1280, height=720):
    params = effect_params(
        effect,
        seed=1,
        scene_id="scene_zoom",
        renderer_version="1.2",
    )
    return params, [
        sample_camera(
            params,
            frame_index=index,
            frame_count=frames,
            fps=fps,
            width=width,
            height=height,
        )
        for index in range(frames)
    ]


def test_slow_push_in_linear_scale_progression() -> None:
    frames = 105
    params, poses = _poses(VisualEffect.slow_push_in, frames=frames)
    scales = [item.scale for item in poses]
    assert poses[0].progress == 0.0
    assert poses[-1].progress == 1.0
    assert scales[0] == PUSH_IN_SCALE[0]
    assert scales[-1] == PUSH_IN_SCALE[1]
    assert scales == sorted(scales)
    deltas = [b - a for a, b in zip(scales[:-1], scales[1:], strict=True)]
    expected = (PUSH_IN_SCALE[1] - PUSH_IN_SCALE[0]) / (frames - 1)
    assert all(abs(delta - expected) < 1e-12 for delta in deltas)
    assert len(set(scales)) == frames
    unique_legacy = {legacy_integer_scale_width(scale, 1280) for scale in scales}
    assert len(unique_legacy) < frames // 2
    xs = [item.center_x for item in poses]
    assert all(abs(x - 640.0) < 1e-9 for x in xs)
    _ = params


def test_slow_pull_out_and_pans_are_linear() -> None:
    frames = 90
    _pull_params, pull = _poses(VisualEffect.slow_pull_out, frames=frames)
    assert pull[0].scale == PULL_OUT_SCALE[0]
    assert pull[-1].scale == PULL_OUT_SCALE[1]
    pull_deltas = [b.scale - a.scale for a, b in zip(pull[:-1], pull[1:], strict=True)]
    assert all(delta < 0 for delta in pull_deltas)
    assert all(abs(delta - pull_deltas[0]) < 1e-12 for delta in pull_deltas)

    _left_params, left = _poses(VisualEffect.pan_left, frames=frames)
    xs = [item.center_x for item in left]
    x_deltas = [b - a for a, b in zip(xs[:-1], xs[1:], strict=True)]
    assert all(delta < 0 for delta in x_deltas)
    assert all(abs(delta - x_deltas[0]) < 1e-9 for delta in x_deltas)
    assert len(set(xs)) == frames
    assert not all(x == int(x) for x in xs[1:-1])

    _right_params, right = _poses(VisualEffect.pan_right, frames=frames)
    assert all(
        b.center_x > a.center_x for a, b in zip(right[:-1], right[1:], strict=True)
    )


def test_handheld_centers_are_fractional_and_unique() -> None:
    frames = 96
    params, poses = _poses(VisualEffect.documentary_handheld, frames=frames)
    assert params.scale_start == HANDHELD_SCALE
    xs = [item.center_x for item in poses]
    ys = [item.center_y for item in poses]
    assert len(set(xs)) == frames
    assert len(set(ys)) == frames
    assert any(x != int(x) for x in xs)
    dx = [abs(b - a) for a, b in zip(xs[:-1], xs[1:], strict=True)]
    assert max(dx) < 4.0
    assert min(dx) < 0.5


def test_motion_progress_bounds() -> None:
    assert motion_progress(0, 1) == 0.0
    assert motion_progress(0, 10) == 0.0
    assert motion_progress(9, 10) == 1.0


def test_motion_filter_uses_perspective_cubic() -> None:
    params, _unused = _poses(VisualEffect.slow_push_in, frames=102)
    graph = motion_filter(
        params,
        duration=3.4,
        width=1280,
        height=720,
        fps=30,
        frame_count=102,
        oversample=1,
    )
    assert "perspective=" in graph
    assert "interpolation=cubic" in graph
    assert "eval=frame" in graph
    assert "zoompan=" not in graph
    assert "trunc(" not in graph
    _ = _unused
