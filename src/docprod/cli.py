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
from docprod.logging_utils import configure_logging
from docprod.media import probe_binary
from docprod.models.enums import JobStatus
from docprod.models.job import JobState
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.models.script import NarrationScript
from docprod.pipeline.scene_planner_stage import execute_scene_planner
from docprod.planning.models import summarize_scene_plan
from docprod.planning.narration_demo import build_narration_demo
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


@app.callback()
def _cli_setup() -> None:
    configure_logging(get_settings())


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
    row("narration", project_dir.narration_json, NarrationScript)
    row("scene plan", project_dir.scene_plan_json, ScenePlan)
    console.print(table)


@app.command("make-narration-demo")
def make_narration_demo(
    project_id: str = typer.Argument(...),
    language: str = typer.Option("tr", "--language", help="Fixture language (tr or en)"),
) -> None:
    """Write a fictional timed narration fixture. No TTS, no network."""
    project_dir, _project = _load_project(project_id)
    script = build_narration_demo(language=language)
    pathmod.ensure_project_layout(project_dir)
    save_model(project_dir.narration_json, script)
    last = script.utterances[-1].end if script.utterances else 0.0
    console.print(
        f"Wrote {len(script.utterances)} utterances "
        f"({last:.1f}s, language={script.language}) to {project_dir.narration_json}"
    )


@app.command("plan-scenes")
def plan_scenes_cmd(
    project_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Ignore cache and replan"),
    profile: str = typer.Option("documentary_v1", "--profile", help="Planner profile name"),
) -> None:
    """Plan scenes from stages/04_narration.json into stages/05_scenes.json."""
    project_dir, project = _load_project(project_id)
    try:
        plan, skipped, input_hash = execute_scene_planner(
            project_dir,
            project_id=project.id,
            random_seed=project.random_seed,
            profile_name=profile,
            force=force,
        )
    except FileNotFoundError as exc:
        _fail(str(exc))
    except ValueError as exc:
        _fail(str(exc))
    except Exception as exc:
        _fail(f"Scene planner failed: {exc}")
    if skipped:
        console.print(
            f"[yellow]Idempotent skip[/yellow]: scene planner input hash {input_hash[:12]}… "
            f"already completed ({len(plan.scenes)} scenes)."
        )
        return
    console.print(
        f"Wrote {len(plan.scenes)} scenes ({plan.total_duration:.1f}s) to "
        f"{project_dir.scene_plan_json}"
    )


@app.command("inspect-scenes")
def inspect_scenes(
    project_id: str = typer.Argument(...),
) -> None:
    """Print a review table and planner statistics."""
    project_dir, _project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"No scene plan at {project_dir.scene_plan_json}")
    try:
        plan = load_model(project_dir.scene_plan_json, ScenePlan)
    except Exception as exc:
        _fail(f"Invalid scene plan: {exc}")
    stats = summarize_scene_plan(plan)
    table = Table(title=f"scenes {project_id}")
    table.add_column("ID", no_wrap=True)
    table.add_column("Start-End", no_wrap=True)
    table.add_column("Dur", justify="right")
    table.add_column("Category")
    table.add_column("Strategy")
    table.add_column("Effect")
    table.add_column("Trans")
    table.add_column("Narration")
    table.add_column("Reason")
    for scene in plan.scenes:
        meta = scene.metadata
        snippet = scene.narration.replace("\n", " ")
        if len(snippet) > 48:
            snippet = snippet[:45] + "..."
        if not snippet:
            snippet = "(bridge)"
        table.add_row(
            scene.id,
            f"{scene.start:.1f}-{scene.end:.1f}",
            f"{scene.duration:.1f}",
            str(meta.get("primary_category", "")),
            scene.asset_strategy.value,
            scene.effect.value,
            scene.transition.value,
            snippet,
            str(meta.get("strategy_reason", "")),
        )
    console.print(table)
    summary = Table(title="summary", show_header=False)
    summary.add_column("k")
    summary.add_column("v")
    summary.add_row("scene_count", str(stats.scene_count))
    summary.add_row("total_duration", f"{stats.total_duration:.2f}s")
    summary.add_row("average_duration", f"{stats.average_scene_duration:.2f}s")
    summary.add_row("min_duration", f"{stats.min_scene_duration:.2f}s")
    summary.add_row("max_duration", f"{stats.max_scene_duration:.2f}s")
    summary.add_row("strategy_counts", json.dumps(stats.strategy_counts))
    summary.add_row("effect_counts", json.dumps(stats.effect_counts))
    summary.add_row("transition_counts", json.dumps(stats.transition_counts))
    summary.add_row("ai_image_to_video_duration", f"{stats.ai_video_duration:.2f}s")
    summary.add_row("ai_image_to_video_fraction", f"{stats.ai_video_fraction:.3f}")
    console.print(summary)


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
