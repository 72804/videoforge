from __future__ import annotations

from datetime import timedelta

from docprod.observability import log_scope
from docprod.product.enums import (
    AssetKind,
    AttemptStatus,
    JobStatus,
    PlanItemType,
    ProjectStatus,
    ProviderBilledStatus,
    ProviderOutcome,
)
from docprod.product.errors import ProductError
from docprod.product.jobs import can_transition
from docprod.product.models import ScriptVersion
from docprod.product.services import ProductService

logger = None


def _log():
    global logger
    if logger is None:
        from docprod.logging_utils import get_logger as _get

        logger = _get("product.worker")
    return logger


class MockGenerationWorker:
    """Advances jobs through real states with local mock bytes. No network."""

    def __init__(
        self,
        service: ProductService,
        worker_id: str = "inline",
        *,
        generation_mode: str = "mock",
        allow_paid_generation: bool = False,
    ) -> None:
        if allow_paid_generation:
            raise ProductError("ALLOW_PAID_GENERATION is false for this phase")
        if generation_mode != "mock":
            raise ProductError("GENERATION_MODE must be mock")
        self.service = service
        self.worker_id = worker_id
        self.lease = timedelta(seconds=30)
        self.generation_mode = generation_mode

    def run_job(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        with log_scope(job_id=job_id, user_id=job.user_id, project_id=job.project_id):
            if (
                job.provider_cost_cap > 0
                and job.reserved_provider_cost - 1e-9 > job.provider_cost_cap
            ):
                self.service.fail_job(
                    job_id,
                    public_message="Provider cost cap exceeded.",
                    error_code="PROVIDER_CAP_EXCEEDED",
                )
                return
            if job.status is JobStatus.COMPLETED:
                return
            if job.status is JobStatus.WAITING_FOR_PAYMENT:
                self.service.start_generation(job.user_id, job.id)
            recovered = self.service.recover_uncertain_paid_attempts(job_id)
            if recovered:
                _log().info("recovered remote operations without resubmit count=%s", len(recovered))
            self._heartbeat(job_id)
            job = self.service.repo.jobs[job_id]
            kind = job.kind
            if kind == "scene_image":
                self._run_scene_image(job_id)
                return
            if kind == "scene_video":
                self._run_scene_video(job_id)
                return
            if kind == "render":
                self._run_render(job_id)
                return
            self._run_full(job_id)

    def _persist(self) -> None:
        repo = self.service.repo
        flush = getattr(repo, "flush_dirty", None)
        session = getattr(repo, "session", None)
        if callable(flush) and session is not None:
            flush()
            session.commit()
            snap = getattr(repo, "snapshot", None)
            if callable(snap):
                snap()

    def _heartbeat(self, job_id: str) -> None:
        try:
            self.service.repo.heartbeat_job(job_id, self.worker_id, lease=self.lease)
        except ProductError:
            pass
        self._persist()

    def _ensure_status(self, job_id: str, target: JobStatus) -> None:
        job = self.service.repo.jobs[job_id]
        if job.status is target:
            return
        if can_transition(job.status, target):
            self.service.advance_job(job_id, target)
            self._heartbeat(job_id)

    def _run_full(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        if job.status is JobStatus.QUEUED:
            self._ensure_status(job_id, JobStatus.PLANNING)
        job = self.service.repo.jobs[job_id]
        if job.status in {JobStatus.PLANNING, JobStatus.RECOVERING_REMOTE}:
            self._ensure_status(job_id, JobStatus.GENERATING_SCRIPT)
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
        if not project.active_script_version_id:
            script = ScriptVersion(
                project_id=project.id,
                body=f"Mock script for: {project.prompt}",
                language=project.language,
            )
            self.service.repo.scripts[script.id] = script
            project.active_script_version_id = script.id
        if not self.service.repo.scenes_for(project.id):
            self.service.ensure_mock_outline(job.user_id, project.id)
        job.progress["script"] = {"completed": 1, "total": 1}
        self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
        scenes = self.service.repo.scenes_for(project.id)
        job.progress.setdefault("images", {"completed": 0, "total": len(scenes)})
        job.progress["images"]["total"] = len(scenes)
        for scene in scenes:
            if scene.locked:
                continue
            if job.progress["images"]["completed"] >= job.progress["images"]["total"]:
                break
            version = self.service._active_version(scene)
            if version.image_asset_version_id and not version.image_stale:
                job.progress["images"]["completed"] += 1
                continue
            self.service.attach_mock_asset(
                job.user_id, scene.id, kind=AssetKind.IMAGE, data=b"mock-still"
            )
            job.progress["images"]["completed"] += 1
            self._heartbeat(job_id)
        self._ensure_status(job_id, JobStatus.GENERATING_VIDEO)
        animate = scenes[:1]
        job.progress.setdefault("video", {"completed": 0, "total": len(animate)})
        job.progress["video"]["total"] = len(animate)
        for scene in animate:
            if scene.locked:
                continue
            existing = [
                a
                for a in self.service.repo.attempts_for_job(job_id)
                if a.item_type is PlanItemType.VIDEO and a.remote_operation_id
            ]
            if not existing:
                self.service.record_attempt(
                    job_id,
                    item_type=PlanItemType.VIDEO,
                    provider="mock",
                    model="mock-video",
                    outcome=ProviderOutcome.SUCCEEDED,
                    billed=ProviderBilledStatus.NOT_BILLED,
                    scene_id=scene.id,
                    status=AttemptStatus.SUBMITTED,
                    remote_operation_id=f"mock-remote-{job_id}",
                    estimated_provider_cost=0.0,
                )
            else:
                # Uncertain paid recovery already inspected remote_operation_id.
                pass
            version = self.service._active_version(scene)
            if not version.video_asset_version_id or version.video_stale:
                self.service.attach_mock_asset(
                    job.user_id, scene.id, kind=AssetKind.VIDEO, data=b"mock-video"
                )
            job.progress["video"]["completed"] = min(
                job.progress["video"]["completed"] + 1, job.progress["video"]["total"]
            )
            self._heartbeat(job_id)
        self._ensure_status(job_id, JobStatus.GENERATING_AUDIO)
        job.progress["audio"] = {"completed": 1, "total": 1}
        self._ensure_status(job_id, JobStatus.RENDERING)
        key = f"projects/{project.id}/renders/{job.id}.mp4"
        self.service.storage.put_bytes(key, b"mock-render", content_type="video/mp4")
        job.progress["render"] = {"completed": 1, "total": 1}
        if self.service.repo.jobs[job_id].status is not JobStatus.COMPLETED:
            self.service.complete_job(job.id, storage_key=key)

    def _finish_after_media(self, job_id: str, project_status: ProjectStatus) -> None:
        self._ensure_status(job_id, JobStatus.GENERATING_AUDIO)
        self._ensure_status(job_id, JobStatus.RENDERING)
        job = self.service.repo.jobs[job_id]
        key = f"projects/{job.project_id}/renders/{job.id}.mp4"
        self.service.storage.put_bytes(key, b"mock-render", content_type="video/mp4")
        self.service.complete_job(job.id, storage_key=key)
        self.service.repo.projects[job.project_id].status = project_status

    def _run_scene_image(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        scene_id = job.target_scene_id
        if not scene_id:
            raise ProductError("scene image job missing target_scene_id")
        if job.status is JobStatus.QUEUED:
            self._ensure_status(job_id, JobStatus.PLANNING)
        self._ensure_status(job_id, JobStatus.GENERATING_SCRIPT)
        self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
        self.service.regenerate_scene_image(job.user_id, scene_id)
        self.service.attach_mock_asset(
            job.user_id, scene_id, kind=AssetKind.IMAGE, data=b"mock-still-v2"
        )
        job.progress["images"] = {"completed": 1, "total": 1}
        self._finish_after_media(job_id, ProjectStatus.PARTIAL)

    def _run_scene_video(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        scene_id = job.target_scene_id
        if not scene_id:
            raise ProductError("scene video job missing target_scene_id")
        if job.status is JobStatus.QUEUED:
            self._ensure_status(job_id, JobStatus.PLANNING)
        self._ensure_status(job_id, JobStatus.GENERATING_SCRIPT)
        self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
        self._ensure_status(job_id, JobStatus.GENERATING_VIDEO)
        self.service.regenerate_scene_video(job.user_id, scene_id)
        self.service.attach_mock_asset(
            job.user_id, scene_id, kind=AssetKind.VIDEO, data=b"mock-video-v2"
        )
        job.progress["video"] = {"completed": 1, "total": 1}
        self._finish_after_media(job_id, ProjectStatus.PARTIAL)

    def _run_render(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        if job.status is JobStatus.QUEUED:
            self._ensure_status(job_id, JobStatus.PLANNING)
        self._ensure_status(job_id, JobStatus.GENERATING_SCRIPT)
        self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
        self._ensure_status(job_id, JobStatus.GENERATING_VIDEO)
        self._ensure_status(job_id, JobStatus.GENERATING_AUDIO)
        job = self.service.advance_job(job_id, JobStatus.RENDERING)
        key = f"projects/{job.project_id}/renders/{job.id}.mp4"
        self.service.storage.put_bytes(key, b"mock-render", content_type="video/mp4")
        job.progress["render"] = {"completed": 1, "total": 1}
        self.service.complete_job(job.id, storage_key=key)
        self.service.record_attempt(
            job.id,
            item_type=PlanItemType.RENDER,
            provider="mock",
            model="ffmpeg-mock",
            outcome=ProviderOutcome.SUCCEEDED,
            billed=ProviderBilledStatus.NOT_BILLED,
        )
