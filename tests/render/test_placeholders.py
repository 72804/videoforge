from __future__ import annotations

import pytest

from docprod.models.enums import AssetStrategy
from docprod.render.ffmpeg import discover_font
from docprod.render.models import PreviewRenderProfile
from docprod.render.placeholders import STRATEGY_COLORS, placeholder_filter
from docprod.storage.paths import RENDERER_VERSION


def test_render_profile_validation() -> None:
    with pytest.raises(ValueError):
        PreviewRenderProfile(width=1279, height=720)
    with pytest.raises(ValueError):
        PreviewRenderProfile(segment_workers=0)
    with pytest.raises(ValueError):
        PreviewRenderProfile(motion_oversample_factor=0)
    ok = PreviewRenderProfile()
    assert ok.width == 1280 and ok.height == 720
    assert ok.motion_oversample_factor == 1
    assert ok.renderer_version == RENDERER_VERSION


def test_placeholder_filter_mentions_strategy() -> None:
    font = discover_font()
    graph = placeholder_filter(
        strategy=AssetStrategy.document,
        scene_id="scene_0003",
        category="document",
        width=160,
        height=120,
        duration=0.5,
        fps=10,
        font=font,
    )
    assert "scene_0003" in graph
    assert "document" in graph
    assert STRATEGY_COLORS[AssetStrategy.document] in graph
