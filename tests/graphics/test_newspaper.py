from __future__ import annotations

from pathlib import Path

from docprod.graphics.document import FORBIDDEN_MARKERS
from docprod.graphics.newspaper import render_newspaper_graphic
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene
from docprod.storage.paths import ProjectPaths


def _news_scene() -> Scene:
    return Scene(
        id="scene_0011",
        start=0.0,
        end=1.0,
        duration=1.0,
        narration="Gazetedeki küçük bir haber kupürü delil gibi duruyordu.",
        visual_intent="Gazetedeki küçük bir haber kupürü delil gibi duruyordu.",
        asset_strategy=AssetStrategy.document,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.tense,
        subtitle="kupür",
        metadata={"primary_category": "news"},
    )


def test_newspaper_graphic_deterministic(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _news_scene()
    first = execute_generate_graphic(paths, scene=scene, seed=3)
    second = execute_generate_graphic(paths, scene=scene, seed=3)
    assert first.graphic_type == "newspaper"
    assert first.output_sha256 == second.output_sha256
    assert second.cache_hit is True
    joined = " ".join(first.text_fields.values())
    assert "lorem" not in joined.lower()
    for marker in FORBIDDEN_MARKERS:
        assert marker.lower() not in joined.lower()
    assert "GÜNLÜK KAYIT" in joined


def test_newspaper_headline_from_narration() -> None:
    image, fields, variant = render_newspaper_graphic(_news_scene(), seed="n")
    assert variant == "newspaper_clipping"
    assert "KUPÜR" in fields["headline"] or "HABER" in fields["headline"]
    assert image.size[0] == 1536
