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
from docprod.exceptions import (
    AlignmentQualityError,
    DossierValidationError,
    MaxPaidRequestsExceededError,
    MissingApiKeyError,
    PaidApiDisabledError,
    PaidApiNotConfirmedError,
    ResearchQualityError,
    ScriptValidationError,
    StockProviderError,
    UnsafeProjectIdError,
    ZeroPlaceholderError,
)
from docprod.logging_utils import configure_logging
from docprod.media import probe_binary
from docprod.models.enums import JobStatus
from docprod.models.job import JobState
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.models.script import NarrationScript
from docprod.pipeline.generate_image_stage import execute_generate_image
from docprod.pipeline.generate_images_batch import execute_generate_images
from docprod.pipeline.preview_render_stage import execute_preview_render
from docprod.pipeline.scene_planner_stage import execute_scene_planner
from docprod.planning.models import summarize_scene_plan
from docprod.planning.narration_demo import build_narration_demo
from docprod.render.ffmpeg import (
    FFmpegError,
    ffmpeg_has_filter,
    ffmpeg_path,
    ffmpeg_version_line,
    probe_media,
)
from docprod.render.models import PreviewRenderProfile, RenderManifest
from docprod.render.renderer import render_debug_scene
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
    path_ffmpeg_ok, _, path_ffmpeg_ver = probe_binary("ffmpeg")
    ffprobe_ok, _, ffprobe_ver = probe_binary("ffprobe")
    try:
        resolved = ffmpeg_path()
        ffmpeg_ok = True
        ffmpeg_ver = ffmpeg_version_line() or resolved
        has_libass = ffmpeg_has_filter("subtitles")
        has_drawtext = ffmpeg_has_filter("drawtext")
    except FFmpegError as exc:
        resolved = None
        ffmpeg_ok = False
        ffmpeg_ver = str(exc)
        has_libass = False
        has_drawtext = False
    table = Table(title="docprod doctor", show_header=False)
    table.add_column("key")
    table.add_column("value")
    table.add_row("package_version", __version__)
    table.add_row("python_version", sys.version.split()[0])
    table.add_row("repo_root", str(pathmod.default_repo_root()))
    table.add_row("projects_root", str(pathmod.default_projects_root()))
    table.add_row("cache_root", str(pathmod.default_cache_root()))
    table.add_row("ALLOW_PAID_APIS", str(settings.allow_paid_apis).lower())
    table.add_row("IMAGE_PROVIDER", settings.image_provider)
    table.add_row(
        "OPENAI_API_KEY_configured",
        str(settings.openai_key_configured()).lower(),
    )
    table.add_row(
        "PEXELS_API_KEY_configured",
        str(settings.pexels_key_configured()).lower(),
    )
    table.add_row("OPENAI_IMAGE_MODEL", settings.openai_image_model)
    table.add_row("OPENAI_TTS_MODEL", settings.openai_tts_model)
    table.add_row("OPENAI_TTS_VOICE", settings.openai_tts_voice)
    table.add_row("RESEARCH_PROVIDER", settings.research_provider)
    table.add_row("RESEARCH_MODEL", settings.research_model)
    table.add_row("DOSSIER_MODEL", settings.dossier_model)
    table.add_row("WRITER_MODEL", settings.writer_model)
    table.add_row("ffmpeg_path", resolved or "NOT FOUND")
    table.add_row(
        "ffmpeg",
        ffmpeg_ver if ffmpeg_ok else (path_ffmpeg_ver or "NOT FOUND"),
    )
    table.add_row(
        "ffprobe",
        ffprobe_ver if ffprobe_ok else "NOT FOUND",
    )
    table.add_row("ffmpeg_libass_subtitles", str(has_libass).lower())
    table.add_row("ffmpeg_drawtext", str(has_drawtext).lower())
    console.print(table)
    if not ffmpeg_ok or not ffprobe_ok:
        raise typer.Exit(2)
    if not has_libass:
        err_console.print(
            "[yellow]Preview burn-in needs libass (`subtitles` filter). "
            "Install Homebrew ffmpeg-full or set DOCPROD_FFMPEG.[/yellow]"
        )
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


@app.command("init-research")
def init_research_cmd(
    project_id: str = typer.Argument(...),
    topic: str = typer.Option(..., "--topic"),
    language: str = typer.Option("tr", "--language"),
    target_minutes: float = typer.Option(7.0, "--target-minutes"),
    content_type: str = typer.Option(
        "documentary / unusual crime / heist",
        "--content-type",
    ),
    audience: str = typer.Option("general adult documentary viewers", "--audience"),
    notes: str = typer.Option("", "--notes"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a project and 00_topic.json. No paid APIs."""
    from docprod.research.models import TopicSpec

    try:
        project_dir = pathmod.project_paths(project_id)
    except UnsafeProjectIdError as exc:
        _fail(str(exc))
    exists = project_dir.project_json.is_file()
    if exists and not force and project_dir.topic_json().is_file():
        _fail(f"Research topic already exists: {project_dir.topic_json()}. Use --force.")
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
        title=topic[:80],
        language=language,
        target_duration_seconds=max(target_minutes, 0.1) * 60.0,
        created_at=created_at,
        updated_at=now,
        random_seed=42,
        metadata={"content_type": content_type},
    )
    pathmod.ensure_project_layout(project_dir)
    save_model(project_dir.project_json, project)
    spec = TopicSpec(
        project_id=project_id,
        topic=topic,
        language=language,
        target_runtime_minutes=target_minutes,
        target_audience=audience,
        content_type=content_type,
        research_notes_optional=notes,
    )
    save_model(project_dir.topic_json(), spec)
    console.print(f"Wrote {project_dir.topic_json()}")


@app.command("research-topic")
def research_topic_cmd(
    project_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(False, "--confirm-paid"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Web-research a topic with OpenAI Responses + web_search. One paid research request."""
    from docprod.pipeline.research_topic import prepare_research, run_research_topic

    project_dir, project = _load_project(project_id)
    if not project_dir.topic_json().is_file():
        _fail("Missing 00_topic.json. Run init-research first.")
    prepared = prepare_research(project_dir)
    console.print(f"topic={prepared.topic.topic}")
    console.print(f"research_model={prepared.model}")
    console.print(f"max_web_tool_calls={prepared.max_tool_calls}")
    console.print("research_objectives=timeline,locations,orgs,quantity/value,")
    console.print("discovery,investigation,legal_outcomes,recovery,disputed_figures")
    for path in prepared.expected_paths:
        console.print(f"expected_path={path}")
    console.print("paid_call_warning=ALLOW_PAID_APIS=true AND --confirm-paid required")
    if dry_run:
        console.print("dry_run=true (zero network calls)")
        return
    try:
        result = run_research_topic(
            project_dir,
            project=project,
            confirm_paid=confirm_paid,
        )
    except (
        PaidApiDisabledError,
        PaidApiNotConfirmedError,
        MissingApiKeyError,
        ResearchQualityError,
    ) as exc:
        _fail(str(exc))
    console.print(
        f"cache_hit={str(result.cache_hit).lower()} "
        f"requests={result.request_count} "
        f"sources={len(result.registry.sources)} "
        f"quality={'pass' if result.quality.passed else 'fail'}"
    )


@app.command("build-dossier")
def build_dossier_cmd(
    project_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(False, "--confirm-paid"),
) -> None:
    """Extract a sourced fact dossier. No web_search. One paid request unless cached."""
    from docprod.pipeline.build_dossier import run_build_dossier

    project_dir, _project = _load_project(project_id)
    try:
        dossier, summary, cache_hit, requests = run_build_dossier(
            project_dir,
            confirm_paid=confirm_paid,
        )
    except (
        PaidApiDisabledError,
        PaidApiNotConfirmedError,
        MissingApiKeyError,
        ResearchQualityError,
        DossierValidationError,
    ) as exc:
        _fail(str(exc))
    console.print(
        f"cache_hit={str(cache_hit).lower()} requests={requests} "
        f"facts={summary.fact_count} unsupported={summary.unsupported_fact_count}"
    )
    console.print(f"dossier {project_dir.research_dossier_json()}")


@app.command("write-script")
def write_script_cmd(
    project_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(False, "--confirm-paid"),
) -> None:
    """Write a Turkish documentary narration from the dossier. No web_search."""
    from docprod.pipeline.research_review import write_research_review
    from docprod.pipeline.write_script import run_write_script

    project_dir, _project = _load_project(project_id)
    try:
        script, cache_hit, requests = run_write_script(
            project_dir,
            confirm_paid=confirm_paid,
        )
    except (
        PaidApiDisabledError,
        PaidApiNotConfirmedError,
        MissingApiKeyError,
        DossierValidationError,
        ScriptValidationError,
    ) as exc:
        _fail(str(exc))
    review = write_research_review(project_dir)
    console.print(
        f"cache_hit={str(cache_hit).lower()} requests={requests} "
        f"words={script.word_count} runtime_min={script.estimated_runtime_minutes:.2f}"
    )
    console.print(f"script {project_dir.story_script_json()}")
    console.print(f"review {project_dir.research_review_md()} ({len(review.split())} review-words)")


@app.command("research-and-write")
def research_and_write_cmd(
    project_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(False, "--confirm-paid"),
) -> None:
    """Run research, dossier, and script in order. Still three independent cached stages."""
    research_topic_cmd(project_id, confirm_paid=confirm_paid, dry_run=False)
    build_dossier_cmd(project_id, confirm_paid=confirm_paid)
    write_script_cmd(project_id, confirm_paid=confirm_paid)


@app.command("inspect-research")
def inspect_research_cmd(project_id: str = typer.Argument(...)) -> None:
    """Show research sources, quality gate, dossier, and usage."""
    from docprod.research.models import (
        DossierValidationSummary,
        ResearchDossier,
        ResearchRawResponse,
        SourceRegistry,
        TopicSpec,
    )
    from docprod.research.validation import evaluate_research_quality

    project_dir, _project = _load_project(project_id)
    table = Table(title=f"research {project_id}", show_header=False)
    table.add_column("k")
    table.add_column("v")
    if project_dir.topic_json().is_file():
        topic = load_model(project_dir.topic_json(), TopicSpec)
        table.add_row("topic", topic.topic)
    if project_dir.research_response_json().is_file():
        raw = load_model(project_dir.research_response_json(), ResearchRawResponse)
        table.add_row("research_model", raw.model)
        table.add_row("web_search_calls", str(raw.usage.web_search_call_count if raw.usage else 0))
        table.add_row("cache_hit", str(raw.cache_hit).lower())
        if raw.usage:
            table.add_row("input_tokens", str(raw.usage.input_tokens))
            table.add_row("output_tokens", str(raw.usage.output_tokens))
            table.add_row("cached_tokens", str(raw.usage.cached_tokens))
            table.add_row("reasoning_tokens", str(raw.usage.reasoning_tokens))
            table.add_row("request_count", str(raw.usage.request_count))
    if project_dir.sources_json().is_file():
        registry = load_model(project_dir.sources_json(), SourceRegistry)
        table.add_row("sources_retained", str(len(registry.sources)))
        domains = {item.domain for item in registry.sources if item.quality_tier != "low"}
        table.add_row("independent_domains", str(len(domains)))
        tiers = {"A": 0, "B": 0, "C": 0, "low": 0}
        for item in registry.sources:
            tiers[item.quality_tier] = tiers.get(item.quality_tier, 0) + 1
        table.add_row("tiers", f"A={tiers['A']} B={tiers['B']} C={tiers['C']} low={tiers['low']}")
        if project_dir.research_report_md().is_file():
            report = project_dir.research_report_md().read_text(encoding="utf-8")
            quality = evaluate_research_quality(report, registry, require=False)
            table.add_row("quality_gate", "pass" if quality.passed else "fail")
            table.add_row("sources_discovered", str(len(registry.sources)))
    if project_dir.research_dossier_json().is_file():
        dossier = load_model(project_dir.research_dossier_json(), ResearchDossier)
        table.add_row("facts", str(len(dossier.facts)))
        table.add_row("timeline_events", str(len(dossier.timeline_events)))
        table.add_row("uncertainties", str(len(dossier.uncertainties)))
        if dossier.usage:
            table.add_row("dossier_model", dossier.model)
            table.add_row("dossier_input_tokens", str(dossier.usage.input_tokens))
            table.add_row("dossier_output_tokens", str(dossier.usage.output_tokens))
            table.add_row("dossier_requests", str(dossier.usage.request_count))
    if project_dir.dossier_validation_json().is_file():
        summary = load_model(project_dir.dossier_validation_json(), DossierValidationSummary)
        table.add_row("unsupported_facts", str(summary.unsupported_fact_count))
    console.print(table)


@app.command("inspect-script")
def inspect_script_cmd(project_id: str = typer.Argument(...)) -> None:
    """Show writer stats, chapters, beats, and coverage."""
    from docprod.writing.models import NarrationScript

    project_dir, _project = _load_project(project_id)
    if not project_dir.story_script_json().is_file():
        _fail("Missing 04_story_script.json")
    script = load_model(project_dir.story_script_json(), NarrationScript)
    table = Table(title=f"script {project_id}", show_header=False)
    table.add_column("k")
    table.add_column("v")
    table.add_row("writer_model", script.writer_model)
    table.add_row("word_count", str(script.word_count))
    table.add_row("estimated_runtime_min", f"{script.estimated_runtime_minutes:.2f}")
    table.add_row("chapters", str(len(script.outline.chapters)))
    table.add_row("beats", str(len(script.beats)))
    if script.validation:
        table.add_row("claims_referenced", str(script.validation.claims_referenced))
        table.add_row("sources_referenced", str(script.validation.sources_referenced))
        table.add_row("unsupported_beats", str(script.validation.unsupported_beat_count))
        table.add_row("target_word_range", str(script.validation.within_target_word_range).lower())
        if script.validation.repetition_notes:
            table.add_row("notes", "; ".join(script.validation.repetition_notes))
    if script.usage:
        table.add_row("input_tokens", str(script.usage.input_tokens))
        table.add_row("output_tokens", str(script.usage.output_tokens))
        table.add_row("request_count", str(script.usage.request_count))
    console.print(table)
    chapters = Table(title="chapters")
    chapters.add_column("id")
    chapters.add_column("title")
    chapters.add_column("beats")
    for item in script.outline.chapters:
        chapters.add_row(item.chapter_id, item.title, ",".join(item.beat_ids))
    console.print(chapters)


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


@app.command("generate-image")
def generate_image_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(
        False,
        "--confirm-paid",
        help="Required for a real paid image API call (with ALLOW_PAID_APIS=true).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even when a matching cached image exists. Still requires --confirm-paid.",
    ),
    archive_as: str = typer.Option(
        "superseded",
        "--archive-as",
        help="Review state stored on the archived previous still (rejected or superseded).",
    ),
) -> None:
    """Generate one documentary still for an ai_image or ai_image_to_video scene."""
    project_dir, _project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    try:
        plan = load_model(project_dir.scene_plan_json, ScenePlan)
    except Exception as exc:
        _fail(f"Invalid scene plan: {exc}")
    if archive_as not in {"rejected", "superseded", "generated", "approved"}:
        _fail(f"Invalid --archive-as {archive_as!r}")
    try:
        manifest = execute_generate_image(
            project_dir,
            plan=plan,
            scene_id=scene_id,
            confirm_paid=confirm_paid,
            force=force,
            archive_as=archive_as,  # type: ignore[arg-type]
            progress=lambda message: console.print(message),
        )
    except (PaidApiDisabledError, PaidApiNotConfirmedError, MissingApiKeyError, ValueError) as exc:
        _fail(str(exc))
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        detail = str(exc)
        if "sk-" in detail.lower() or "authorization" in detail.lower():
            detail = "OpenAI request failed (details omitted to avoid leaking secrets)"
        if status is not None:
            _fail(f"OpenAI image request failed (HTTP {status}): {detail}")
        _fail(f"OpenAI image request failed: {detail}")
    if manifest.cache_hit:
        console.print(f"Reused cached image {manifest.output_path}")
        return
    console.print(
        f"Wrote {project_dir.scene_image_path(scene_id)} "
        f"sha256={manifest.output_sha256} request_hash={manifest.request_hash}"
    )


@app.command("generate-images")
def generate_images_cmd(
    project_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(
        False,
        "--confirm-paid",
        help="Required for real paid image API calls (with ALLOW_PAID_APIS=true).",
    ),
    max_paid_requests: int = typer.Option(
        ...,
        "--max-paid-requests",
        min=0,
        help="Abort before any call if planned paid requests exceed this cap.",
    ),
    workers: int = typer.Option(1, "--workers", min=1, help="Reserved; paid calls stay serial."),
    force_scene: list[str] = typer.Option(
        [],
        "--force-scene",
        help="Regenerate this scene even if cached/approved. Repeatable.",
    ),
    only_scene: list[str] = typer.Option(
        [],
        "--only",
        help="Limit the batch to these scene ids. Repeatable.",
    ),
    archive_as: list[str] = typer.Option(
        [],
        "--archive-as",
        help="Per-scene archive review state as scene_id=rejected|superseded. Repeatable.",
    ),
) -> None:
    """Generate stills for ai_image and ai_image_to_video scenes. No AI video."""
    project_dir, _project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    try:
        plan = load_model(project_dir.scene_plan_json, ScenePlan)
    except Exception as exc:
        _fail(f"Invalid scene plan: {exc}")
    archive_map: dict[str, str] = {}
    for item in archive_as:
        if "=" not in item:
            _fail(f"Invalid --archive-as {item!r}; expected scene_id=state")
        scene_key, state = item.split("=", 1)
        if state not in {"rejected", "superseded", "generated", "approved"}:
            _fail(f"Invalid archive state {state!r}")
        archive_map[scene_key.strip()] = state
    try:
        manifest = execute_generate_images(
            project_dir,
            plan=plan,
            confirm_paid=confirm_paid,
            max_paid_requests=max_paid_requests,
            workers=workers,
            force_scene_ids=force_scene,
            only_scene_ids=only_scene,
            archive_as_by_scene=archive_map,  # type: ignore[arg-type]
            progress=lambda message: console.print(message),
        )
    except MaxPaidRequestsExceededError as exc:
        _fail(str(exc))
    except (PaidApiDisabledError, PaidApiNotConfirmedError, MissingApiKeyError, ValueError) as exc:
        _fail(str(exc))
    except Exception as exc:
        _fail(str(exc))
    from docprod.models.enums import AssetStrategy
    from docprod.render.contact_sheet import contact_sheet_from_plan

    sheet = contact_sheet_from_plan(
        project_dir,
        [
            (item.id, item.asset_strategy.value)
            for item in plan.scenes
            if item.asset_strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
        ],
        output=project_dir.contact_sheet(),
    )
    console.print(
        f"generated={manifest.generated} skipped={manifest.skipped} failed={manifest.failed}"
    )
    console.print(f"Batch manifest {project_dir.image_batch_manifest()}")
    if sheet:
        console.print(f"Contact sheet {sheet}")


@app.command("generate-graphics")
def generate_graphics_cmd(
    project_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Regenerate even when cached."),
) -> None:
    """Render local document/newspaper/map graphics. No paid APIs."""
    from docprod.graphics.renderer import execute_generate_graphics
    from docprod.render.contact_sheet import build_contact_sheet

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    manifests = execute_generate_graphics(
        project_dir,
        plan=plan,
        seed=project.random_seed,
        force=force,
        progress=lambda message: console.print(message),
    )
    entries: list[tuple[str, str, Path]] = []
    for item in manifests:
        output = Path(item.output_path)
        if not output.is_file():
            output = (project_dir.root / item.output_path).resolve()
        entries.append((item.scene_id, item.graphic_type, output))
    sheet = build_contact_sheet(
        project_dir,
        entries,
        columns=2,
        output=project_dir.graphics_contact_sheet,
    )
    hits = sum(1 for item in manifests if item.cache_hit)
    console.print(f"graphics={len(manifests)} cache_hits={hits}")
    if sheet:
        console.print(f"Graphics contact sheet {sheet}")


@app.command("generate-narration")
def generate_narration_cmd(
    project_id: str = typer.Argument(...),
    confirm_paid: bool = typer.Option(
        False,
        "--confirm-paid",
        help="Required for the real OpenAI TTS + Whisper calls.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Write script and print plan; no API."),
) -> None:
    """Generate one continuous Turkish narration and word-align it. Two paid calls."""
    from docprod.pipeline.generate_narration import generate_narration, prepare_narration

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    settings = get_settings()
    prepared = prepare_narration(project_dir, plan, settings=settings)
    console.print(f"provider={prepared.provider}")
    console.print(f"model={prepared.model}")
    console.print(f"voice={prepared.voice}")
    console.print(f"speed={prepared.speed}")
    console.print(f"character_count={prepared.character_count}")
    console.print(f"output_path={prepared.output_wav}")
    console.print(f"instructions={prepared.instructions}")
    console.print(f"script_path={project_dir.narration_script_txt()}")
    if dry_run:
        console.print(prepared.script.text)
        return
    try:
        result = generate_narration(
            project_dir,
            project=project,
            plan=plan,
            confirm_paid=confirm_paid,
            settings=settings,
        )
    except (
        PaidApiDisabledError,
        PaidApiNotConfirmedError,
        MissingApiKeyError,
        AlignmentQualityError,
    ) as exc:
        _fail(str(exc))
    console.print(
        f"tts_requests={result.tts_request_count} "
        f"whisper_requests={result.whisper_request_count} "
        f"duration={result.meta.duration:.3f}s "
        f"match={result.alignment.match_fraction:.3f}"
    )
    console.print(f"timeline {project_dir.runtime_timeline_json()}")


@app.command("search-stock")
def search_stock_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str | None = typer.Option(None, "--scene", help="Limit search to one scene id"),
) -> None:
    """Search Pexels for stock-video scenes. Metadata and contact sheets only; no download."""
    from docprod.pipeline.search_stock import search_stock

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    try:
        manifest = search_stock(
            project_dir,
            project=project,
            plan=plan,
            scene_id=scene_id,
        )
    except (MissingApiKeyError, StockProviderError) as exc:
        _fail(str(exc))
    console.print(
        "ratelimit "
        f"limit={manifest.ratelimit_limit} "
        f"remaining={manifest.ratelimit_remaining} "
        f"reset={manifest.ratelimit_reset}"
    )
    for item in manifest.scenes:
        console.print(
            f"{item.scene_id} queries={item.queries} unique={len(item.candidates)} "
            f"sheet={item.contact_sheet}"
        )
    console.print(f"Wrote {project_dir.stock_candidates_json()}")


@app.command("select-stock")
def select_stock_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
    pexels_video_id: str = typer.Argument(...),
) -> None:
    """Download a previously searched Pexels candidate and normalize a scene clip."""
    from docprod.pipeline.search_stock import select_stock

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    try:
        meta = select_stock(
            project_dir,
            project=project,
            plan=plan,
            scene_id=scene_id,
            video_id=pexels_video_id,
        )
    except (MissingApiKeyError, StockProviderError) as exc:
        _fail(str(exc))
    console.print(
        f"Selected {scene_id} pexels={meta.provider_video_id} "
        f"sha256={meta.sha256} clip={meta.clip_path}"
    )


@app.command("select-stock-auto")
def select_stock_auto_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
    fallback_video_id: str | None = typer.Option(
        None, "--fallback-id", help="Pexels video id if no preferred candidate scores."
    ),
) -> None:
    """Pick the highest-scoring non-rejected candidate. Prefer human select-stock first."""
    from docprod.pipeline.search_stock import select_stock_auto

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    try:
        meta = select_stock_auto(
            project_dir,
            project=project,
            plan=plan,
            scene_id=scene_id,
            fallback_video_id=fallback_video_id,
        )
    except (MissingApiKeyError, StockProviderError) as exc:
        _fail(str(exc))
    console.print(f"Auto-selected {scene_id} pexels={meta.provider_video_id} sha256={meta.sha256}")


@app.command("render-graphic")
def render_graphic_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Generate one local documentary graphic for debugging."""
    from docprod.graphics.renderer import execute_generate_graphics

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    if not any(scene.id == scene_id for scene in plan.scenes):
        _fail(f"Unknown scene id {scene_id!r}")
    manifests = execute_generate_graphics(
        project_dir,
        plan=plan,
        seed=project.random_seed,
        force=force,
        scene_id=scene_id,
        progress=lambda message: console.print(message),
    )
    if not manifests:
        _fail(f"Scene {scene_id} does not use a local graphic strategy")
    console.print(f"Wrote {manifests[0].output_path} sha256={manifests[0].output_sha256}")


@app.command("approve-image")
def approve_image_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
) -> None:
    """Mark an existing generated still as approved. No API call."""
    from docprod.pipeline.generate_image_stage import _load_success_manifest
    from docprod.providers.image_review import set_review_state

    project_dir, _project = _load_project(project_id)
    existing = _load_success_manifest(project_dir.scene_image_meta(scene_id))
    if existing is None:
        _fail(f"No successful image metadata for {scene_id}")
    record = set_review_state(
        project_dir,
        scene_id,
        "approved",
        artifact_sha256=existing.output_sha256,
        note="pinned without regenerating",
    )
    console.print(f"Approved {scene_id} sha256={record.artifact_sha256}")


@app.command("reject-image")
def reject_image_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
) -> None:
    """Mark a generated still as rejected without deleting it."""
    from docprod.pipeline.generate_image_stage import _load_success_manifest
    from docprod.providers.image_review import set_review_state

    project_dir, _project = _load_project(project_id)
    existing = _load_success_manifest(project_dir.scene_image_meta(scene_id))
    sha = existing.output_sha256 if existing else None
    record = set_review_state(project_dir, scene_id, "rejected", artifact_sha256=sha)
    console.print(f"Rejected {scene_id} (file kept) sha256={record.artifact_sha256}")


@app.command("render-preview")
def render_preview_cmd(
    project_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Re-run the preview_render stage"),
    workers: int = typer.Option(2, "--workers", min=1, help="Parallel FFmpeg scene workers"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Re-encode all scene segments"),
    allow_placeholders: bool = typer.Option(
        False,
        "--allow-placeholders",
        help="Allow debug placeholder cards (tests and incomplete projects).",
    ),
    narrated: bool = typer.Option(
        False,
        "--narrated",
        help="Render documentary_preview_narrated.mp4 from the runtime timeline.",
    ),
) -> None:
    """Render a 720p documentary preview with FFmpeg. No paid APIs."""
    import time

    from docprod.pipeline.inspect_assets import require_zero_placeholders

    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    try:
        plan = load_model(project_dir.scene_plan_json, ScenePlan)
    except Exception as exc:
        _fail(f"Invalid scene plan: {exc}")
    if not allow_placeholders:
        try:
            require_zero_placeholders(project_dir, plan)
        except ZeroPlaceholderError as exc:
            _fail(str(exc))
    runtime_plan = plan
    if narrated:
        from docprod.pipeline.generate_narration import load_runtime_plan, retime_stock_for_runtime

        if not project_dir.runtime_timeline_json().is_file():
            _fail("Missing runtime timeline. Run generate-narration first.")
        if not project_dir.narration_master_wav().is_file():
            _fail("Missing master narration WAV.")
        runtime_plan = load_runtime_plan(project_dir, plan)
        try:
            retime_stock_for_runtime(project_dir, plan=runtime_plan, seed=project.random_seed)
        except ValueError as exc:
            _fail(str(exc))
    stats = summarize_scene_plan(runtime_plan)
    console.print(
        f"Preview render {project_id}: {stats.scene_count} scenes, "
        f"{stats.total_duration:.2f}s plan, strategies={stats.strategy_counts}"
    )
    started = time.perf_counter()
    try:
        if narrated:
            from docprod.render.models import PreviewRenderProfile
            from docprod.render.renderer import render_preview

            result = render_preview(
                project_dir,
                project=project,
                plan=runtime_plan,
                profile=PreviewRenderProfile(),
                workers=workers,
                use_cache=not no_cache,
                progress=lambda message: console.print(message),
                output_mp4=project_dir.preview_narrated_mp4(),
                manifest_path=project_dir.preview_narrated_manifest(),
                captions_srt=project_dir.captions_narrated_srt(),
                captions_ass=project_dir.captions_narrated_ass(),
                narration_wav=project_dir.narration_master_wav(),
            )
            skipped = False
        else:
            result, skipped, _hash = execute_preview_render(
                project_dir,
                project=project,
                plan=runtime_plan,
                force=force,
                workers=workers,
                use_cache=not no_cache,
                progress=lambda message: console.print(message),
            )
    except FFmpegError as exc:
        _fail(str(exc))
    except Exception as exc:
        _fail(f"Preview render failed: {exc}")
    elapsed = time.perf_counter() - started
    if skipped:
        console.print(
            f"[yellow]Idempotent skip[/yellow]: preview already valid "
            f"({result.manifest.final_output})"
        )
        return
    console.print(
        f"Wrote {result.manifest.final_output} in {elapsed:.1f}s "
        f"({result.rendered_segments} rendered, {result.cache_hits} cache hits, "
        f"{result.manifest.actual_duration:.2f}s, "
        f"{result.manifest.width}x{result.manifest.height})"
    )


@app.command("render-scene")
def render_scene_cmd(
    project_id: str = typer.Argument(...),
    scene_id: str = typer.Argument(...),
) -> None:
    """Render a single scene segment into artifacts/render/preview/debug/."""
    project_dir, project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    try:
        dest = render_debug_scene(
            project_dir,
            project=project,
            plan=plan,
            scene_id=scene_id,
            profile=PreviewRenderProfile(),
        )
    except (FFmpegError, ValueError) as exc:
        _fail(str(exc))
    console.print(f"Wrote debug scene {dest}")


@app.command("inspect-render")
def inspect_render_cmd(
    project_id: str = typer.Argument(...),
    narrated: bool = typer.Option(False, "--narrated"),
) -> None:
    """Inspect the preview MP4 and render manifest."""
    project_dir, _project = _load_project(project_id)
    table = Table(title=f"render {project_id}", show_header=False)
    table.add_column("k")
    table.add_column("v")
    final = project_dir.preview_narrated_mp4() if narrated else project_dir.preview_mp4
    manifest_path = (
        project_dir.preview_narrated_manifest() if narrated else project_dir.preview_manifest
    )
    table.add_row("final_path", str(final))
    table.add_row("exists", str(final.is_file()).lower())
    if not final.is_file():
        console.print(table)
        return
    try:
        probe = probe_media(final)
        valid = probe.has_video and probe.has_audio
        table.add_row("valid", str(valid).lower())
        table.add_row("duration", f"{probe.duration:.3f}s")
        table.add_row("resolution", f"{probe.width}x{probe.height}")
        table.add_row("fps", str(probe.fps))
        table.add_row("video_codec", str(probe.video_codec))
        table.add_row("pixel_format", str(probe.pixel_format))
        table.add_row("audio_codec", str(probe.audio_codec))
        table.add_row("audio", f"{probe.sample_rate}Hz/{probe.channels}ch")
    except FFmpegError as exc:
        table.add_row("valid", "no")
        table.add_row("error", str(exc))
        console.print(table)
        return
    table.add_row(
        "captions.srt",
        str(
            (
                project_dir.captions_narrated_srt() if narrated else project_dir.captions_srt
            ).is_file()
        ).lower(),
    )
    table.add_row(
        "captions.ass",
        str(
            (
                project_dir.captions_narrated_ass() if narrated else project_dir.captions_ass
            ).is_file()
        ).lower(),
    )
    if narrated and project_dir.narration_master_meta().is_file():
        from docprod.audio.models import NarrationMasterMeta

        nmeta = load_model(project_dir.narration_master_meta(), NarrationMasterMeta)
        if nmeta.loudness:
            table.add_row("input_i", nmeta.loudness.get("input_i", ""))
            table.add_row("input_tp", nmeta.loudness.get("input_tp", ""))
    if manifest_path.is_file():
        manifest = load_model(manifest_path, RenderManifest)
        table.add_row("scene_count", str(manifest.scene_count))
        table.add_row("segment_count", str(len(manifest.segments)))
        table.add_row("cache_hits", str(sum(1 for s in manifest.segments if s.cache_hit)))
        table.add_row("fallback_count", str(manifest.fallback_count))
        table.add_row("final_sha256", manifest.final_output_sha256 or "")
        table.add_row("font", manifest.font_path or "")
        console.print(table)
        sources = Table(title="visual sources")
        sources.add_column("scene")
        sources.add_column("strategy")
        sources.add_column("source")
        sources.add_column("rendered")
        for item in manifest.segments:
            sources.add_row(
                item.scene_id,
                item.strategy.value if hasattr(item.strategy, "value") else str(item.strategy),
                item.source_asset or "",
                item.strategy_rendered or "",
            )
        console.print(sources)
        fallbacks = [s for s in manifest.segments if s.fallback_used]
        if fallbacks:
            fb = Table(title="effect fallbacks")
            fb.add_column("scene")
            fb.add_column("requested")
            fb.add_column("rendered")
            for item in fallbacks:
                fb.add_row(item.scene_id, item.effect_requested.value, item.effect_rendered.value)
            console.print(fb)
    else:
        console.print(table)


@app.command("inspect-assets")
def inspect_assets_cmd(
    project_id: str = typer.Argument(...),
    runtime: bool = typer.Option(False, "--runtime"),
) -> None:
    """List resolved visual sources for every scene. Fails if any placeholder remains."""
    from docprod.pipeline.inspect_assets import inspect_assets, placeholder_scene_ids

    project_dir, _project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    rows = inspect_assets(project_dir, plan, runtime=runtime)
    table = Table(title=f"assets {project_id}")
    table.add_column("scene")
    table.add_column("strategy")
    table.add_column("source")
    table.add_column("label")
    table.add_column("planned")
    table.add_column("runtime")
    table.add_column("stock_ok")
    for row in rows:
        table.add_row(
            row.scene_id,
            row.strategy_requested,
            row.source_type,
            row.source_label,
            f"{row.planned_duration:.2f}",
            "" if row.runtime_duration is None else f"{row.runtime_duration:.2f}",
            "" if row.stock_covers_runtime is None else str(row.stock_covers_runtime).lower(),
        )
    console.print(table)
    missing = placeholder_scene_ids(rows)
    console.print(f"placeholders={len(missing)}")
    if missing:
        _fail("Placeholder visuals remain for: " + ", ".join(missing))


@app.command("inspect-narration")
def inspect_narration_cmd(
    project_id: str = typer.Argument(...),
) -> None:
    """Show TTS, alignment, and runtime timeline status."""
    from docprod.audio.models import AlignmentReport, NarrationMasterMeta, RuntimeTimeline
    from docprod.audio.script import tokenize_display

    project_dir, _project = _load_project(project_id)
    if not project_dir.scene_plan_json.is_file():
        _fail(f"Missing scene plan: {project_dir.scene_plan_json}")
    plan = load_model(project_dir.scene_plan_json, ScenePlan)
    table = Table(title=f"narration {project_id}", show_header=False)
    table.add_column("k")
    table.add_column("v")
    if project_dir.narration_master_meta().is_file():
        meta = load_model(project_dir.narration_master_meta(), NarrationMasterMeta)
        table.add_row("model", meta.model)
        table.add_row("voice", meta.voice)
        table.add_row("audio_duration", f"{meta.duration:.3f}s")
        table.add_row("tts_requests", str(meta.tts_request_count))
        table.add_row("whisper_requests", str(meta.whisper_request_count))
    script = project_dir.narration_script_txt()
    if script.is_file():
        text = script.read_text(encoding="utf-8")
        table.add_row("script_chars", str(len(text.strip())))
        table.add_row("script_words", str(len(tokenize_display(text))))
    if project_dir.narration_alignment_json().is_file():
        alignment = load_model(project_dir.narration_alignment_json(), AlignmentReport)
        table.add_row("matched_fraction", f"{alignment.match_fraction:.4f}")
        table.add_row("matched", str(alignment.matched_word_count))
        table.add_row("interpolated", str(alignment.interpolated_word_count))
        table.add_row("unmatched", str(alignment.unmatched_word_count))
        table.add_row("quality_passed", str(alignment.quality_passed).lower())
    if project_dir.runtime_timeline_json().is_file():
        timeline = load_model(project_dir.runtime_timeline_json(), RuntimeTimeline)
        durs = [item.duration for item in timeline.scenes]
        table.add_row("runtime_scenes", str(len(timeline.scenes)))
        table.add_row("runtime_duration", f"{timeline.total_duration:.3f}s")
        table.add_row("min_scene", f"{min(durs):.3f}s")
        table.add_row("max_scene", f"{max(durs):.3f}s")
        if project_dir.narration_master_meta().is_file():
            meta = load_model(project_dir.narration_master_meta(), NarrationMasterMeta)
            if meta.loudness:
                table.add_row("loudness_input_i", meta.loudness.get("input_i", ""))
                table.add_row("loudness_input_tp", meta.loudness.get("input_tp", ""))
    console.print(table)
    if project_dir.runtime_timeline_json().is_file():
        timeline = load_model(project_dir.runtime_timeline_json(), RuntimeTimeline)
        scenes = Table(title="scene durations")
        scenes.add_column("scene")
        scenes.add_column("planned")
        scenes.add_column("runtime")
        scenes.add_column("snippet")
        planned = {item.id: item.duration for item in plan.scenes}
        for item in timeline.scenes:
            scenes.add_row(
                item.scene_id,
                f"{planned.get(item.scene_id, 0):.2f}",
                f"{item.duration:.2f}",
                item.narration[:48],
            )
        console.print(scenes)


@app.command("audit-motion")
def audit_motion_cmd(
    project_id: str = typer.Argument(...),
) -> None:
    """Audit camera-motion continuity of preview segments via signalstats YDIF."""
    from docprod.render.motion_audit import MotionStatus, audit_records

    project_dir, project = _load_project(project_id)
    if not project_dir.preview_manifest.is_file():
        _fail(f"Missing render manifest: {project_dir.preview_manifest}")
    manifest = load_model(project_dir.preview_manifest, RenderManifest)
    rows = audit_records(
        project_dir.preview_segments_dir,
        manifest.segments,
        seed=project.random_seed,
        renderer_version=manifest.renderer_version,
    )
    table = Table(title=f"motion audit {project_id}")
    table.add_column("Scene")
    table.add_column("Requested")
    table.add_column("Rendered")
    table.add_column("Frames", justify="right")
    table.add_column("Near-static", justify="right")
    table.add_column("Longest hold", justify="right")
    table.add_column("Median YDIF", justify="right")
    table.add_column("P90 YDIF", justify="right")
    table.add_column("Max YDIF", justify="right")
    table.add_column("Status")
    counts: dict[str, int] = {status.value: 0 for status in MotionStatus}
    for row in rows:
        counts[row.status.value] = counts.get(row.status.value, 0) + 1
        table.add_row(
            row.scene_id,
            row.effect_requested.value,
            row.effect_rendered.value,
            str(row.frames),
            str(row.near_static),
            str(row.longest_hold),
            f"{row.median_ydif:.4f}",
            f"{row.p90_ydif:.4f}",
            f"{row.max_ydif:.4f}",
            row.status.value,
        )
    console.print(table)
    console.print(
        f"SMOOTH={counts[MotionStatus.SMOOTH.value]} "
        f"STATIC_EXPECTED={counts[MotionStatus.STATIC_EXPECTED.value]} "
        f"REVIEW={counts[MotionStatus.REVIEW.value]} "
        f"FAIL={counts[MotionStatus.FAIL.value]}"
    )
    if counts[MotionStatus.FAIL.value]:
        raise typer.Exit(1)


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
