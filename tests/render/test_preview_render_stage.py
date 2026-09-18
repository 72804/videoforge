from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from docprod.cli import app
from docprod.models.enums import StageStatus, VisualEffect
from docprod.models.job import JobState
from docprod.models.project import Project
from docprod.pipeline.preview_render_stage import STAGE_NAME, execute_preview_render
from docprod.render.models import TINY_TEST_PROFILE, RenderManifest
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import project_paths
from tests.render.helpers import mini_plan, mini_scene

runner = CliRunner()


def _project(pid: str) -> Project:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Project(
        id=pid,
        title="Tiny",
        language="tr",
        target_duration_seconds=2,
        created_at=now,
        updated_at=now,
        random_seed=3,
    )


def _seed_project(projects_root: Path, pid: str = "tiny") -> None:
    paths = project_paths(pid, projects_root=projects_root)
    paths.root.mkdir(parents=True, exist_ok=True)
    save_model(paths.project_json, _project(pid))
    save_model(
        paths.scene_plan_json,
        mini_plan(
            mini_scene("scene_0001", 0.0, 0.4, subtitle="Merhaba dünya"),
            mini_scene(
                "scene_0002",
                0.4,
                0.8,
                subtitle="İkinci",
                effect=VisualEffect.none,
            ),
            project_id=pid,
        ),
    )


def test_preview_stage_writes_outputs_and_job(projects_root: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "docprod.pipeline.preview_render_stage.DEFAULT_PROFILE",
        TINY_TEST_PROFILE,
    )
    monkeypatch.setattr(
        "docprod.cli.PreviewRenderProfile",
        lambda: TINY_TEST_PROFILE,
    )
    _seed_project(projects_root)
    paths = project_paths("tiny", projects_root=projects_root)
    project = load_model(paths.project_json, Project)
    from docprod.models.scene import ScenePlan

    plan = load_model(paths.scene_plan_json, ScenePlan)
    result, skipped, _ = execute_preview_render(
        paths,
        project=project,
        plan=plan,
        profile=TINY_TEST_PROFILE,
        workers=1,
    )
    assert skipped is False
    assert paths.preview_mp4.is_file()
    assert paths.captions_srt.is_file()
    assert paths.captions_ass.is_file()
    manifest = load_model(paths.preview_manifest, RenderManifest)
    assert manifest.scene_count == 2
    job = load_model(paths.job_json, JobState)
    record = next(item for item in job.stages if item.name == STAGE_NAME)
    assert record.status is StageStatus.completed
    assert record.output_hash == result.manifest.final_output_sha256

    again, skipped2, _ = execute_preview_render(
        paths,
        project=project,
        plan=plan,
        profile=TINY_TEST_PROFILE,
        workers=1,
    )
    assert skipped2 is True
    assert again.manifest.final_output_sha256 == result.manifest.final_output_sha256

    forced, skipped3, _ = execute_preview_render(
        paths,
        project=project,
        plan=plan,
        profile=TINY_TEST_PROFILE,
        workers=1,
        force=True,
        use_cache=True,
    )
    assert skipped3 is False
    assert forced.cache_hits == 2

    plan.scenes[0] = plan.scenes[0].model_copy(update={"subtitle": "Yeni metin"})
    from docprod.models.scene import ScenePlan

    mutated = ScenePlan(
        project_id=plan.project_id,
        scenes=plan.scenes,
        total_duration=plan.total_duration,
    )
    save_model(paths.scene_plan_json, mutated)
    changed, skipped4, _ = execute_preview_render(
        paths,
        project=project,
        plan=mutated,
        profile=TINY_TEST_PROFILE,
        workers=1,
    )
    assert skipped4 is False
    assert changed.manifest.input_hash != result.manifest.input_hash

    paths.preview_mp4.write_bytes(b"not-an-mp4")
    repaired, skipped5, _ = execute_preview_render(
        paths,
        project=project,
        plan=mutated,
        profile=TINY_TEST_PROFILE,
        workers=1,
    )
    assert skipped5 is False
    assert repaired.manifest.final_output_sha256 != "not"


def test_render_cli_tiny(projects_root: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "docprod.pipeline.preview_render_stage.DEFAULT_PROFILE",
        TINY_TEST_PROFILE,
    )
    monkeypatch.setattr("docprod.cli.PreviewRenderProfile", lambda: TINY_TEST_PROFILE)
    _seed_project(projects_root, "cliproj")
    preview = runner.invoke(app, ["render-preview", "cliproj", "--workers", "1"])
    assert preview.exit_code == 0, preview.output
    inspect = runner.invoke(app, ["inspect-render", "cliproj"])
    assert inspect.exit_code == 0, inspect.output
    assert "h264" in inspect.output or "video_codec" in inspect.output
    one = runner.invoke(app, ["render-scene", "cliproj", "scene_0001"])
    assert one.exit_code == 0, one.output
    paths = project_paths("cliproj", projects_root=projects_root)
    assert (paths.preview_debug_dir / "scene_0001.mp4").is_file()
