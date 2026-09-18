from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from docprod.cli import app
from docprod.models.scene import ScenePlan
from docprod.storage.json_store import load_model

runner = CliRunner()


def test_doctor_runs_successfully() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "ALLOW_PAID_APIS" in result.output
    assert "false" in result.output.lower()


def test_init_project_cli(projects_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "init-project",
            "demo",
            "--title",
            "Demo",
            "--language",
            "tr",
            "--duration",
            "30",
        ],
    )
    assert result.exit_code == 0, result.output
    project_file = projects_root / "demo" / "project.json"
    assert project_file.is_file()
    payload = json.loads(project_file.read_text(encoding="utf-8"))
    assert payload["title"] == "Demo"
    assert payload["language"] == "tr"
    assert (projects_root / "demo" / "artifacts" / "render").is_dir()


def test_duplicate_init_rejected(projects_root: Path) -> None:
    args = [
        "init-project",
        "demo",
        "--title",
        "Demo",
        "--language",
        "tr",
        "--duration",
        "30",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, args)
    assert second.exit_code != 0
    assert "already exists" in second.output


def test_force_init_preserves_artifact(projects_root: Path) -> None:
    args = [
        "init-project",
        "demo",
        "--title",
        "Demo",
        "--language",
        "tr",
        "--duration",
        "30",
    ]
    assert runner.invoke(app, args).exit_code == 0
    marker = projects_root / "demo" / "artifacts" / "render" / "keep.txt"
    marker.write_text("stay", encoding="utf-8")
    forced = runner.invoke(app, [*args, "--title", "Demo 2", "--force"])
    assert forced.exit_code == 0, forced.output
    assert marker.read_text(encoding="utf-8") == "stay"
    payload = json.loads((projects_root / "demo" / "project.json").read_text(encoding="utf-8"))
    assert payload["title"] == "Demo 2"


def test_demo_generation_deterministic(projects_root: Path) -> None:
    init = runner.invoke(
        app,
        [
            "init-project",
            "demo",
            "--title",
            "Demo",
            "--language",
            "tr",
            "--duration",
            "30",
            "--seed",
            "99",
        ],
    )
    assert init.exit_code == 0, init.output
    first = runner.invoke(app, ["make-demo", "demo"])
    second = runner.invoke(app, ["make-demo", "demo"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    path = projects_root / "demo" / "stages" / "05_scenes.json"
    text_one = path.read_text(encoding="utf-8")
    # regenerate and compare
    assert runner.invoke(app, ["make-demo", "demo"]).exit_code == 0
    text_two = path.read_text(encoding="utf-8")
    assert text_one == text_two
    plan = load_model(path, ScenePlan)
    assert 8 <= len(plan.scenes) <= 12
    assert abs(plan.total_duration - 30.0) < 0.05
    strategies = {scene.asset_strategy for scene in plan.scenes}
    assert "placeholder" in strategies
    assert "ai_image" in strategies
    assert "stock_video" in strategies
    assert "document" in strategies
    assert "map" in strategies
    assert "generated_graphic" in strategies


def test_generate_image_help_is_single_scene() -> None:
    result = runner.invoke(app, ["generate-image", "--help"])
    assert result.exit_code == 0, result.output
    assert "--confirm-paid" in result.output
    assert "SCENE_ID" in result.output.upper() or "scene_id" in result.output.lower()


def test_export_schemas_valid_json(tmp_path: Path) -> None:
    out = tmp_path / "schemas"
    result = runner.invoke(app, ["export-schemas", str(out)])
    assert result.exit_code == 0, result.output
    files = list(out.glob("*.schema.json"))
    assert len(files) == 5
    for file in files:
        payload = json.loads(file.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert "properties" in payload or "$defs" in payload or "title" in payload
