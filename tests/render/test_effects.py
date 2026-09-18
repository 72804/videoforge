from __future__ import annotations

from docprod.models.enums import VisualEffect
from docprod.render.effects import EFFECT_IMPLEMENTATION, effect_params, resolve_effect


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
        renderer_version="1.0",
    )
    b = effect_params(
        VisualEffect.documentary_handheld,
        seed=42,
        scene_id="scene_0004",
        renderer_version="1.0",
    )
    c = effect_params(
        VisualEffect.documentary_handheld,
        seed=99,
        scene_id="scene_0004",
        renderer_version="1.0",
    )
    assert a == b
    assert a.handheld_phase != c.handheld_phase or a.pan_x0 != c.pan_x0


def test_fallback_mapping_recorded() -> None:
    rendered, fallback = resolve_effect(VisualEffect.parallax_2_5d)
    assert fallback is True
    assert rendered is VisualEffect.slow_push_in
    native, native_fb = resolve_effect(VisualEffect.slow_push_in)
    assert native_fb is False
    assert native is VisualEffect.slow_push_in
