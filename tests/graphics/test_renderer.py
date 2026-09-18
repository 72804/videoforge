from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.render.helpers import mini_plan

from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import Scene
from docprod.render.contact_sheet import build_contact_sheet
from docprod.render.ffmpeg import probe_media
from docprod.render.models import TINY_TEST_PROFILE
from docprod.render.renderer import render_preview
from docprod.render.still import resolve_scene_visual
from docprod.storage.paths import ProjectPaths


def _project() -> Project:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Project(
        id="tiny",
        title="Tiny",
        language="tr",
        target_duration_seconds=2,
        created_at=now,
        updated_at=now,
        random_seed=7,
    )


def _scene(
    scene_id: str,
    narration: str,
    strategy: AssetStrategy,
    effect: VisualEffect,
    category: str,
) -> Scene:
    return Scene(
        id=scene_id,
        start=0.0,
        end=0.4,
        duration=0.4,
        narration=narration,
        visual_intent=narration,
        asset_strategy=strategy,
        effect=effect,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        metadata={"primary_category": category},
    )


def test_renderer_selects_local_document_over_placeholder(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    scene = _scene(
        "scene_0008",
        "polise haber verdi ve çantanın içindeki raporu yüksek sesle",
        AssetStrategy.document,
        VisualEffect.newspaper_reveal,
        "document",
    )
    execute_generate_graphic(paths, scene=scene, seed=7)
    visual = resolve_scene_visual(paths, scene)
    assert visual is not None
    assert visual.kind == "local_graphic"
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    record = result.manifest.segments[0]
    assert record.source_asset == "local_graphic"
    assert "placeholder" not in record.ffmpeg_command_summary
    assert "still-image" in record.ffmpeg_command_summary


def test_map_scene_uses_map_asset_and_valid_mp4(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    scene = _scene(
        "scene_0012",
        "Haritada işaretli rota kuzey kapısına gidiyordu.",
        AssetStrategy.map,
        VisualEffect.map_route,
        "map_or_travel",
    )
    execute_generate_graphic(paths, scene=scene, seed=7)
    visual = resolve_scene_visual(paths, scene)
    assert visual is not None
    assert visual.kind == "local_map"
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    record = result.manifest.segments[0]
    assert record.source_asset == "local_map"
    assert record.effect_rendered is VisualEffect.map_route
    assert record.fallback_used is False
    assert "map-route-frames" in record.ffmpeg_command_summary
    probe = probe_media(paths.preview_segments_dir / "scene_0012.mp4")
    assert probe.has_video
    assert probe.width == TINY_TEST_PROFILE.width
    assert probe.height == TINY_TEST_PROFILE.height
    assert probe.pixel_format == "yuv420p"


def test_graphics_contact_sheet(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _scene(
        "scene_0011",
        "Gazetedeki küçük bir haber kupürü delil gibi duruyordu.",
        AssetStrategy.document,
        VisualEffect.slow_push_in,
        "news",
    )
    manifest = execute_generate_graphic(paths, scene=scene, seed=7)
    output = paths.root / manifest.output_path
    sheet = build_contact_sheet(
        paths,
        [
            (manifest.scene_id, manifest.graphic_type, output),
            (manifest.scene_id, "copy", output),
        ],
        columns=2,
        output=paths.graphics_contact_sheet,
    )
    assert sheet is not None and sheet.is_file()
    assert sheet.name == "graphics_contact_sheet.jpg"
