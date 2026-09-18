from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from docprod.cli import app
from docprod.models.enums import StageStatus
from docprod.models.job import JobState
from docprod.models.scene import ScenePlan
from docprod.pipeline.scene_planner_stage import STAGE_NAME, execute_scene_planner
from docprod.storage.hashing import content_hash
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import project_paths

runner = CliRunner()


def _init_and_narration(projects_root: Path, project_id: str = "planner") -> None:
    result = runner.invoke(
        app,
        [
            "init-project",
            project_id,
            "--title",
            "Planner",
            "--language",
            "tr",
            "--duration",
            "60",
            "--seed",
            "42",
        ],
    )
    assert result.exit_code == 0, result.output
    demo = runner.invoke(app, ["make-narration-demo", project_id, "--language", "tr"])
    assert demo.exit_code == 0, demo.output


def test_stage_writes_files_and_job(projects_root: Path) -> None:
    _init_and_narration(projects_root)
    planned = runner.invoke(app, ["plan-scenes", "planner"])
    assert planned.exit_code == 0, planned.output
    paths = project_paths("planner", projects_root=projects_root)
    assert paths.narration_json.is_file()
    assert paths.scene_plan_json.is_file()
    plan = load_model(paths.scene_plan_json, ScenePlan)
    assert plan.scenes
    job = load_model(paths.job_json, JobState)
    record = next(item for item in job.stages if item.name == STAGE_NAME)
    assert record.status is StageStatus.completed
    assert record.input_hash
    assert record.output_hash == content_hash(plan)


def test_idempotent_skip_and_force(projects_root: Path) -> None:
    _init_and_narration(projects_root)
    first = runner.invoke(app, ["plan-scenes", "planner"])
    second = runner.invoke(app, ["plan-scenes", "planner"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Idempotent skip" in second.output
    forced = runner.invoke(app, ["plan-scenes", "planner", "--force"])
    assert forced.exit_code == 0, forced.output
    assert "Idempotent skip" not in forced.output


def test_changed_narration_invalidates_hash(projects_root: Path) -> None:
    _init_and_narration(projects_root)
    assert runner.invoke(app, ["plan-scenes", "planner"]).exit_code == 0
    paths = project_paths("planner", projects_root=projects_root)
    from docprod.models.script import NarrationScript

    script = load_model(paths.narration_json, NarrationScript)
    utterances = list(script.utterances)
    utterances[0] = utterances[0].model_copy(update={"text": utterances[0].text + " ekstra."})
    script = NarrationScript(
        language=script.language,
        full_text=script.full_text + " ekstra.",
        utterances=utterances,
    )
    save_model(paths.narration_json, script)
    result = runner.invoke(app, ["plan-scenes", "planner"])
    assert result.exit_code == 0, result.output
    assert "Idempotent skip" not in result.output


def test_failed_stage_does_not_write_partial_plan(projects_root: Path, monkeypatch) -> None:
    _init_and_narration(projects_root, "broken")
    paths = project_paths("broken", projects_root=projects_root)
    assert not paths.scene_plan_json.is_file()

    def boom(self, payload):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(
        "docprod.pipeline.scene_planner_stage.ScenePlannerStage.run",
        boom,
    )
    result = runner.invoke(app, ["plan-scenes", "broken"])
    assert result.exit_code != 0
    assert not paths.scene_plan_json.is_file()
    job = load_model(paths.job_json, JobState)
    record = next(item for item in job.stages if item.name == STAGE_NAME)
    assert record.status is StageStatus.failed
    assert "exploded" in (record.error or "")


def test_inspect_scenes_cli(projects_root: Path) -> None:
    _init_and_narration(projects_root)
    assert runner.invoke(app, ["plan-scenes", "planner"]).exit_code == 0
    inspect = runner.invoke(app, ["inspect-scenes", "planner"])
    assert inspect.exit_code == 0, inspect.output
    assert "scene_count" in inspect.output
    assert "ai_image_to_video_fraction" in inspect.output


def test_turkish_narration_demo_command(projects_root: Path) -> None:
    _init_and_narration(projects_root)
    from docprod.models.script import NarrationScript

    paths = project_paths("planner", projects_root=projects_root)
    script = load_model(paths.narration_json, NarrationScript)
    assert script.language == "tr"
    assert any(utt.end - utt.start > 6.0 for utt in script.utterances)
    assert any(utt.end - utt.start < 2.0 for utt in script.utterances)


def test_execute_helper_matches_cli(projects_root: Path) -> None:
    _init_and_narration(projects_root, "helper")
    paths = project_paths("helper", projects_root=projects_root)
    plan, skipped, _hash = execute_scene_planner(
        paths,
        project_id="helper",
        random_seed=42,
        force=False,
    )
    assert not skipped
    plan2, skipped2, _ = execute_scene_planner(
        paths,
        project_id="helper",
        random_seed=42,
        force=False,
    )
    assert skipped2
    assert content_hash(plan) == content_hash(plan2)
