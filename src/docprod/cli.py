from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from docprod import __version__
from docprod.config import get_settings
from docprod.demo import build_demo_scene_plan
from docprod.exceptions import UnsafeProjectIdError
from docprod.media import probe_binary
from docprod.models.enums import JobStatus
from docprod.models.job import JobState
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.models.script import NarrationScript
from docprod.storage import paths as pathmod
from docprod.storage.json_store import load_model, save_model

app = typer.Typer(
    name="docprod",
    help="Local-first documentary production pipeline.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _fail(message: str, code: int = 1) -> None:
    err_console.print(f"[red]{message}[/red]")
    raise typer.Exit(code)


def _load_project(project_id: str) -> tuple[pathmod.ProjectPaths, Project]:
    try:
        project_dir = pathmod.project_paths(project_id)
    except UnsafeProjectIdError as exc:
        _fail(str(exc))
    if not project_dir.project_json.is_file():
        _fail(f"Project not found: {project_dir.project_json}")
    try:
        project = load_model(project_dir.project_json, Project)
    except Exception as exc:  # noqa: BLE001 — CLI should surface validation errors
        _fail(f"Invalid project.json: {exc}")
    return project_dir, project


@app.command()
def doctor() -> None:
    """Print toolchain and safety status."""
    settings = get_settings()
    ffmpeg_ok, _, ffmpeg_ver = probe_binary("ffmpeg")
    ffprobe_ok, _, ffprobe_ver = probe_binary("ffprobe")
    table = Table(title="docprod doctor", show_header=False)
    table.add_column("key")
    table.add_column("value")
    table.add_row("package_version", __version__)
    table.add_row("python_version", sys.version.split()[0])
    table.add_row("repo_root", str(pathmod.default_repo_root()))
    table.add_row("projects_root", str(pathmod.default_projects_root()))
    table.add_row("cache_root", str(pathmod.default_cache_root()))
    table.add_row("ALLOW_PAID_APIS", str(settings.allow_paid_apis).lower())
    table.add_row(
        "ffmpeg",
        ffmpeg_ver if ffmpeg_ok else "NOT FOUND",
    )
    table.add_row(
        "ffprobe",
        ffprobe_ver if ffprobe_ok else "NOT FOUND",
    )
    console.print(table)
    if not ffmpeg_ok or not ffprobe_ok:
        raise typer.Exit(2)


@app.command("init-project")
def init_project(
    project_id: str = typer.Argument(..., help="Filesystem-safe project id, e.g. atm_story_001"),
    title: str = typer.Option(..., "--title", help="Human-readable title"),
    language: str = typer.Option("en", "--language", help="Primary language code"),
    duration: float = typer.Option(..., "--duration", help="Target duration in seconds"),
    seed: int = typer.Option(42, "--seed", help="Deterministic random seed"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace project.json without deleting artifacts",
    ),
) -> None:
    """Create a project directory and project.json."""
    try:
        project_dir = pathmod.project_paths(project_id)
    except UnsafeProjectIdError as exc:
        _fail(str(exc))

    exists = project_dir.project_json.is_file()
    if exists and not force:
        _fail(f"Project already exists: {project_dir.root}. Use --force to replace project.json.")

    now = _utc_now()
    created_at = now
    if exists:
        try:
            existing = load_model(project_dir.project_json, Project)
            created_at = existing.created_at
        except Exception:
            created_at = now

    project = Project(
        id=project_id,
        title=title,
        language=language,
        target_duration_seconds=duration,
        created_at=created_at,
        updated_at=now,
        random_seed=seed,
        metadata={},
    )
    pathmod.ensure_project_layout(project_dir)
    save_model(project_dir.project_json, project)

    if not project_dir.job_json.is_file() or not exists:
        job = JobState(
            project_id=project_id,
            status=JobStatus.pending,
            created_at=created_at,
            updated_at=now,
            current_stage=None,
            stages=[],
        )
        save_model(project_dir.job_json, job)

    action = "Updated" if exists else "Created"
    console.print(f"{action} project [bold]{project_id}[/bold] at {project_dir.root}")


@app.command("show-project")
def show_project(
    project_id: str = typer.Argument(...),
) -> None:
    """Pretty-print validated project.json."""
    _, project = _load_project(project_id)
    console.print_json(data=project.model_dump(mode="json"))


@app.command("make-demo")
def make_demo(
    project_id: str = typer.Argument(...),
) -> None:
    """Write a deterministic demo scene plan. No AI, no network."""
    project_dir, project = _load_project(project_id)
    plan = build_demo_scene_plan(project.id, project.random_seed)
    pathmod.ensure_project_layout(project_dir)
    save_model(project_dir.scene_plan_json, plan)
    console.print(
        f"Wrote {len(plan.scenes)} demo scenes "
        f"({plan.total_duration:.1f}s) to {project_dir.scene_plan_json}"
    )


@app.command()
def status(
    project_id: str = typer.Argument(...),
) -> None:
    """Show whether core artifacts exist and validate them."""
    try:
        project_dir = pathmod.project_paths(project_id)
    except UnsafeProjectIdError as exc:
        _fail(str(exc))

    table = Table(title=f"status {project_id}")
    table.add_column("artifact")
    table.add_column("present")
    table.add_column("valid")
    table.add_column("detail")

    def row(label: str, path: Path, model_type: type) -> None:
        if not path.is_file():
            table.add_row(label, "no", "—", str(path))
            return
        try:
            load_model(path, model_type)
            table.add_row(label, "yes", "yes", str(path))
        except Exception as exc:
            table.add_row(label, "yes", "no", str(exc))

    row("project.json", project_dir.project_json, Project)
    row("job.json", project_dir.job_json, JobState)
    row("scene plan", project_dir.scene_plan_json, ScenePlan)
    console.print(table)


@app.command("export-schemas")
def export_schemas(
    output_dir: Path = typer.Argument(..., help="Directory to write JSON Schema files"),
) -> None:
    """Export Pydantic JSON Schemas for core models."""
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "project": Project,
        "narration_script": NarrationScript,
        "scene": Scene,
        "scene_plan": ScenePlan,
        "job_state": JobState,
    }
    for name, model in mapping.items():
        path = output_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8")
        console.print(f"Wrote {path}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
