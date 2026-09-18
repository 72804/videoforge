from __future__ import annotations

from datetime import UTC, datetime

from docprod.models.enums import JobStatus, StageStatus
from docprod.models.job import JobState, StageRecord
from docprod.models.project import Project
from docprod.models.scene import ScenePlan
from docprod.pipeline.stage import PipelineStage
from docprod.render.ffmpeg import FFmpegError, probe_media
from docprod.render.models import PreviewRenderProfile, RenderManifest
from docprod.render.renderer import (
    PreviewRenderResult,
    render_input_hash,
    render_preview,
)
from docprod.render.stats import duration_ok
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import PREVIEW_RENDER_STAGE, ProjectPaths, ensure_project_layout

STAGE_NAME = PREVIEW_RENDER_STAGE
DEFAULT_PROFILE = PreviewRenderProfile()


class PreviewRenderStage(PipelineStage):
    name = STAGE_NAME

    def run(self, payload: dict) -> PreviewRenderResult:
        return render_preview(
            payload["paths"],
            project=payload["project"],
            plan=payload["plan"],
            profile=payload["profile"],
            workers=payload.get("workers"),
            use_cache=payload.get("use_cache", True),
            progress=payload.get("progress"),
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _load_or_create_job(paths: ProjectPaths, project_id: str) -> JobState:
    if paths.job_json.is_file():
        return load_model(paths.job_json, JobState)
    stamp = _now()
    return JobState(
        project_id=project_id,
        status=JobStatus.pending,
        created_at=stamp,
        updated_at=stamp,
        current_stage=None,
        stages=[],
    )


def _upsert_stage(job: JobState, record: StageRecord) -> JobState:
    stages = [item for item in job.stages if item.name != record.name]
    stages.append(record)
    status = JobStatus.running
    if record.status is StageStatus.failed:
        status = JobStatus.failed
    elif record.status is StageStatus.completed:
        status = JobStatus.completed
    return job.model_copy(
        update={
            "stages": stages,
            "updated_at": record.finished_at or record.started_at or job.updated_at,
            "current_stage": record.name,
            "status": status,
        }
    )


def _stage_record(job: JobState, name: str) -> StageRecord | None:
    for item in job.stages:
        if item.name == name:
            return item
    return None


def _final_is_valid(paths: ProjectPaths, profile: PreviewRenderProfile, expected: float) -> bool:
    if not paths.preview_mp4.is_file() or not paths.preview_manifest.is_file():
        return False
    try:
        probe = probe_media(paths.preview_mp4)
        if not probe.has_video or not probe.has_audio:
            return False
        if probe.width != profile.width or probe.height != profile.height:
            return False
        if not duration_ok(expected, probe.duration, profile.fps):
            return False
        file_sha256(paths.preview_mp4)
        load_model(paths.preview_manifest, RenderManifest)
        return True
    except (OSError, FFmpegError, ValueError):
        return False


def execute_preview_render(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    profile: PreviewRenderProfile | None = None,
    force: bool = False,
    workers: int | None = None,
    use_cache: bool = True,
    progress=None,
) -> tuple[PreviewRenderResult, bool, str]:
    profile = profile or DEFAULT_PROFILE
    ensure_project_layout(paths)
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    input_hash = render_input_hash(plan, project, profile)
    job = _load_or_create_job(paths, project.id)
    existing = _stage_record(job, STAGE_NAME)
    expected = sum(
        max(1, round(scene.end * profile.fps) - round(scene.start * profile.fps))
        for scene in plan.scenes
    ) / profile.fps
    if (
        not force
        and existing is not None
        and existing.status is StageStatus.completed
        and existing.input_hash == input_hash
        and _final_is_valid(paths, profile, expected)
    ):
        manifest = load_model(paths.preview_manifest, RenderManifest)
        if existing.output_hash == manifest.final_output_sha256:
            result = PreviewRenderResult(
                manifest=manifest,
                skipped=True,
                rendered_segments=0,
                cache_hits=len(manifest.segments),
            )
            return result, True, input_hash

    started = _now()
    running = StageRecord(
        name=STAGE_NAME,
        status=StageStatus.running,
        started_at=started,
        input_hash=input_hash,
        metadata={"renderer_version": profile.renderer_version, "profile": profile.name},
    )
    job = _upsert_stage(job, running)
    save_model(paths.job_json, job)
    stage = PreviewRenderStage()
    try:
        result = stage.run(
            {
                "paths": paths,
                "project": project,
                "plan": plan,
                "profile": profile,
                "workers": workers,
                "use_cache": use_cache,
                "progress": progress,
            }
        )
        completed = running.model_copy(
            update={
                "status": StageStatus.completed,
                "finished_at": _now(),
                "output_hash": result.manifest.final_output_sha256,
                "error": None,
            }
        )
        job = _upsert_stage(job, completed)
        save_model(paths.job_json, job)
        return result, False, input_hash
    except Exception as exc:
        failed = running.model_copy(
            update={
                "status": StageStatus.failed,
                "finished_at": _now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        job = _upsert_stage(job, failed)
        save_model(paths.job_json, job)
        raise
