from __future__ import annotations

from pathlib import Path

from docprod.graphics.document import (
    FORBIDDEN_MARKERS,
    classify_document_layout,
    render_document_graphic,
)
from docprod.graphics.fonts import discover_sans_font, font_renders_turkish
from docprod.graphics.models import GraphicManifest
from docprod.graphics.renderer import execute_generate_graphic, graphic_source_hash
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths


def _doc_scene(
    scene_id: str,
    narration: str,
    *,
    category: str = "document",
    strategy: AssetStrategy = AssetStrategy.document,
    effect: VisualEffect = VisualEffect.photo_table,
) -> Scene:
    return Scene(
        id=scene_id,
        start=0.0,
        end=1.0,
        duration=1.0,
        narration=narration,
        visual_intent=narration,
        asset_strategy=strategy,
        effect=effect,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        metadata={"primary_category": category},
    )


def test_document_graphic_is_deterministic(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _doc_scene(
        "scene_0008",
        "polise haber verdi ve çantanın içindeki raporu yüksek sesle",
    )
    first = execute_generate_graphic(paths, scene=scene, seed=42)
    second = execute_generate_graphic(paths, scene=scene, seed=42)
    assert first.output_sha256 == second.output_sha256
    assert second.cache_hit is True
    png = paths.scene_graphic_png("scene_0008")
    assert file_sha256(png) == first.output_sha256
    meta = load_model(paths.scene_graphic_meta("scene_0008"), GraphicManifest)
    assert meta.output_sha256 == first.output_sha256
    assert graphic_source_hash(scene, seed=42) == first.request_hash


def test_force_regenerates_document(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _doc_scene("scene_0008", "polise haber verdi ve raporu okudu.")
    first = execute_generate_graphic(paths, scene=scene, seed=7)
    forced = execute_generate_graphic(paths, scene=scene, seed=7, force=True)
    assert forced.cache_hit is False
    assert forced.output_sha256 == first.output_sha256


def test_turkish_glyphs_and_no_official_seals() -> None:
    scene = _doc_scene(
        "scene_0008",
        "polise haber verdi ve çantanın içindeki raporu yüksek sesle",
    )
    image, fields, variant = render_document_graphic(scene, seed="42:scene_0008:1.0")
    assert variant == "police_report"
    joined = " ".join(fields.values())
    for marker in FORBIDDEN_MARKERS:
        assert marker.lower() not in joined.lower()
    assert "ç" in joined or "ı" in scene.narration
    font = discover_sans_font()
    assert font_renders_turkish(font)
    extrema = image.convert("L").getextrema()
    assert extrema[0] != extrema[1]


def test_court_layout_differs_from_police() -> None:
    police = _doc_scene("scene_0008", "polise haber verdi ve raporu okudu.")
    court = _doc_scene(
        "scene_0015",
        "Mahkeme tutanağı henüz yoktu; sadece o rapor vardı.",
        category="document",
    )
    assert classify_document_layout(police) == "police_report"
    assert classify_document_layout(court) == "court_folder"
    a, fa, _va = render_document_graphic(police, seed="s")
    b, fb, _vb = render_document_graphic(court, seed="s")
    assert fa["heading"] != fb["heading"]
    assert a.tobytes() != b.tobytes()
