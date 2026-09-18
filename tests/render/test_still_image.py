from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import GenerationSpec, Scene
from docprod.providers.image_config import GeneratedImageManifest
from docprod.render.contact_sheet import build_contact_sheet
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.models import TINY_TEST_PROFILE
from docprod.render.renderer import render_preview
from docprod.render.still import still_fit_filter
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import save_model
from docprod.storage.paths import ProjectPaths
from tests.render.helpers import mini_plan


def _project(pid: str = "tiny") -> Project:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Project(
        id=pid,
        title="Tiny",
        language="tr",
        target_duration_seconds=2,
        created_at=now,
        updated_at=now,
        random_seed=7,
    )


def test_matching_aspect_ratio_uses_proportional_scale() -> None:
    filt = still_fit_filter(1536, 864, 1280, 720)
    assert filt == "scale=1280:720:flags=lanczos"
    assert "crop" not in filt
    assert "force_original_aspect_ratio" not in filt


def test_mismatched_aspect_ratio_center_crops_without_stretch() -> None:
    filt = still_fit_filter(200, 100, 160, 120)
    assert "force_original_aspect_ratio=increase" in filt
    assert "crop=160:120" in filt
    assert "scale=160:120:" in filt
    assert "setsar" not in filt


def _write_jpeg(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:s={width}x{height}",
            "-frames:v",
            "1",
            str(path),
        ]
    )


def _ai_scene() -> Scene:
    return Scene(
        id="scene_0003",
        start=0.0,
        end=0.4,
        duration=0.4,
        narration="Hello",
        visual_intent="Test card",
        asset_strategy=AssetStrategy.ai_image,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle="Hello",
        generation=GenerationSpec(image_prompt="a red mug on a table"),
        metadata={"primary_category": "generic"},
    )


def test_renderer_uses_real_image_when_present(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    scene = _ai_scene()
    image = paths.scene_image_path("scene_0003")
    _write_jpeg(image, 320, 180)
    save_model(
        paths.scene_image_meta("scene_0003"),
        GeneratedImageManifest(
            provider="openai",
            model="gpt-image-2.5-flare",
            scene_id="scene_0003",
            prompt="a red mug on a table",
            size="320x180",
            quality="medium",
            output_format="jpeg",
            source_scene_hash="abc",
            request_hash="def",
            output_path="artifacts/visuals/scene_0003/image.jpg",
            output_sha256=file_sha256(image),
            generation_status="success",
        ),
    )
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    record = result.manifest.segments[0]
    assert "still-image" in record.ffmpeg_command_summary
    probe = probe_media(paths.preview_segments_dir / "scene_0003.mp4")
    assert probe.width == TINY_TEST_PROFILE.width
    assert probe.height == TINY_TEST_PROFILE.height
    assert probe.pixel_format == "yuv420p"


def test_keyframe_still_used_for_ai_image_to_video(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    scene = Scene(
        id="scene_0004",
        start=0.0,
        end=0.4,
        duration=0.4,
        narration="Adam yürüdü.",
        visual_intent="Walk",
        asset_strategy=AssetStrategy.ai_image_to_video,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle="Walk",
        generation=GenerationSpec(image_prompt="a man walking on a platform"),
        metadata={"primary_category": "action"},
    )
    image = paths.scene_image_path("scene_0004")
    _write_jpeg(image, 320, 180)
    save_model(
        paths.scene_image_meta("scene_0004"),
        GeneratedImageManifest(
            provider="openai",
            model="gpt-image-2.5-flare",
            scene_id="scene_0004",
            prompt="a man walking on a platform",
            size="320x180",
            quality="medium",
            output_format="jpeg",
            source_scene_hash="abc",
            request_hash="def",
            output_path="artifacts/visuals/scene_0004/image.jpg",
            output_sha256=file_sha256(image),
            generation_status="success",
        ),
    )
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    record = result.manifest.segments[0]
    assert record.source_asset == "generated_still"
    assert record.strategy_requested is AssetStrategy.ai_image_to_video
    assert record.strategy_rendered == "ai_image_keyframe_preview"
    assert "still-image" in record.ffmpeg_command_summary
    assert probe_media(paths.preview_segments_dir / "scene_0004.mp4").pixel_format == "yuv420p"


def test_contact_sheet_creation(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    one = paths.scene_image_path("scene_0002")
    two = paths.scene_image_path("scene_0004")
    _write_jpeg(one, 320, 180)
    _write_jpeg(two, 320, 180)
    sheet = build_contact_sheet(
        paths,
        [
            ("scene_0002", "ai_image", one),
            ("scene_0004", "ai_image_to_video", two),
        ],
    )
    assert sheet is not None and sheet.is_file()
    probe = probe_media(sheet)
    assert probe.width == 640
    assert probe.height >= 180


def test_renderer_falls_back_to_placeholder_when_image_absent(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    scene = _ai_scene()
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    assert "placeholder" in result.manifest.segments[0].ffmpeg_command_summary
