from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docprod.models.enums import VisualEffect
from docprod.models.project import Project
from docprod.render.effects import effect_params
from docprod.render.ffmpeg import probe_media
from docprod.render.models import TINY_TEST_PROFILE
from docprod.render.renderer import render_preview, segment_input_hash
from docprod.storage.paths import ProjectPaths
from tests.render.helpers import mini_plan, mini_scene


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


def test_segment_hash_changes_with_scene_and_profile() -> None:
    scene = mini_scene("scene_0001", 0.0, 0.4)
    project = _project()
    params = effect_params(
        scene.effect,
        seed=project.random_seed,
        scene_id=scene.id,
        renderer_version="1.0",
    )
    h1 = segment_input_hash(
        scene, project=project, profile=TINY_TEST_PROFILE, params_rendered=params.rendered.value
    )
    changed = scene.model_copy(update={"subtitle": "changed caption"})
    h2 = segment_input_hash(
        changed, project=project, profile=TINY_TEST_PROFILE, params_rendered=params.rendered.value
    )
    other = TINY_TEST_PROFILE.model_copy(update={"crf": 30})
    h3 = segment_input_hash(
        scene, project=project, profile=other, params_rendered=params.rendered.value
    )
    h4 = segment_input_hash(
        scene, project=project, profile=TINY_TEST_PROFILE, params_rendered=params.rendered.value
    )
    assert h1 != h2
    assert h1 != h3
    assert h1 == h4


def test_tiny_scene_and_concat_render(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    plan = mini_plan(
        mini_scene(
            "scene_0001",
            0.0,
            0.4,
            subtitle="Birinci sahne ç ğ ı",
            effect=VisualEffect.slow_push_in,
        ),
        mini_scene(
            "scene_0002",
            0.4,
            0.8,
            subtitle="İkinci sahne",
            effect=VisualEffect.parallax_2_5d,
        ),
    )
    result = render_preview(
        paths,
        project=_project(),
        plan=plan,
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=True,
    )
    assert paths.preview_mp4.is_file()
    probe = probe_media(paths.preview_mp4)
    assert probe.has_video and probe.has_audio
    assert probe.width == 160 and probe.height == 120
    assert probe.video_codec == "h264"
    assert probe.audio_codec == "aac"
    assert abs(probe.duration - result.manifest.expected_duration) < 0.25
    assert result.manifest.segments[1].fallback_used is True
    assert result.manifest.segments[1].effect_rendered is VisualEffect.slow_push_in
    assert result.manifest.segments[0].fallback_used is False
    again = render_preview(
        paths,
        project=_project(),
        plan=plan,
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=True,
    )
    assert again.cache_hits == 2
    assert again.rendered_segments == 0
