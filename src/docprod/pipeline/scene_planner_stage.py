from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from docprod.models.enums import JobStatus, StageStatus
from docprod.models.job import JobState, StageRecord
from docprod.models.scene import ScenePlan
from docprod.models.script import NarrationScript
from docprod.pipeline.stage import PipelineStage
from docprod.planning.planner import plan_scenes
from docprod.planning.profile import ScenePlannerProfile, get_profile
from docprod.storage.hashing import content_hash
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import SCENE_PLANNER_STAGE, ProjectPaths, ensure_project_layout

STAGE_NAME = SCENE_PLANNER_STAGE


class ScenePlannerStage(PipelineStage):
    name = STAGE_NAME

    def run(self, payload: dict[str, Any]) -> ScenePlan:
        script = payload["script"]
        if not isinstance(script, NarrationScript):
            script = NarrationScript.model_validate(script)
        profile = payload["profile"]
        if not isinstance(profile, ScenePlannerProfile):
            profile = ScenePlannerProfile.model_validate(profile)
        return plan_scenes(
            project_id=str(payload["project_id"]),
            script=script,
            random_seed=int(payload["random_seed"]),
            profile=profile,
        )


def planner_input_hash(
    *,
    script: NarrationScript,
    random_seed: int,
    profile: ScenePlannerProfile,
) -> str:
    return content_hash(
        {
            "narration": script.model_dump(mode="json"),
            "random_seed": random_seed,
            "profile": profile.model_dump(mode="json"),
            "planner_version": profile.planner_version,
        }
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
    return job.model_copy(
        update={
            "stages": stages,
            "updated_at": record.finished_at or record.started_at or job.updated_at,
            "current_stage": record.name,
            "status": (
                JobStatus.failed
                if record.status is StageStatus.failed
                else JobStatus.running
                if record.status is StageStatus.running
                else JobStatus.completed
            ),
        }
    )


def _stage_record(job: JobState, name: str) -> StageRecord | None:
    for item in job.stages:
        if item.name == name:
            return item
    return None


def execute_scene_planner(
    paths: ProjectPaths,
    *,
    project_id: str,
    random_seed: int,
    profile_name: str = "documentary_v1",
    force: bool = False,
) -> tuple[ScenePlan, bool, str]:
    """Run or skip the scene planner. Returns (plan, skipped, input_hash)."""
    ensure_project_layout(paths)
    if not paths.narration_json.is_file():
        raise FileNotFoundError(f"Missing narration fixture: {paths.narration_json}")
    script = load_model(paths.narration_json, NarrationScript)
    profile = get_profile(profile_name)
    input_hash = planner_input_hash(script=script, random_seed=random_seed, profile=profile)
    job = _load_or_create_job(paths, project_id)
    existing = _stage_record(job, STAGE_NAME)
    if (
        not force
        and existing is not None
        and existing.status is StageStatus.completed
        and existing.input_hash == input_hash
        and paths.scene_plan_json.is_file()
    ):
        plan = load_model(paths.scene_plan_json, ScenePlan)
        output_hash = content_hash(plan)
        if existing.output_hash == output_hash:
            return plan, True, input_hash

    started = _now()
    running = StageRecord(
        name=STAGE_NAME,
        status=StageStatus.running,
        started_at=started,
        finished_at=None,
        input_hash=input_hash,
        output_hash=None,
        error=None,
        metadata={"profile": profile.name, "planner_version": profile.planner_version},
    )
    job = _upsert_stage(job, running)
    save_model(paths.job_json, job)
    stage = ScenePlannerStage()
    try:
        plan = stage.run(
            {
                "project_id": project_id,
                "script": script,
                "random_seed": random_seed,
                "profile": profile,
            }
        )
        save_model(paths.scene_plan_json, plan)
        output_hash = content_hash(plan)
        completed = running.model_copy(
            update={
                "status": StageStatus.completed,
                "finished_at": _now(),
                "output_hash": output_hash,
                "error": None,
            }
        )
        job = _upsert_stage(job, completed)
        save_model(paths.job_json, job)
        return plan, False, input_hash
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
