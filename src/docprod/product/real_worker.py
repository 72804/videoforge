from __future__ import annotations

import hashlib
from datetime import timedelta

from docprod.observability import log_scope
from docprod.product.engine_bridge import (
    FIRST_CANARY_PROVIDERS,
    build_engine_spec,
    freeze_plan,
    frozen_plan_payload,
    persist_engine_outline,
)
from docprod.product.enums import (
    AssetKind,
    AttemptStatus,
    JobStatus,
    PlanItemType,
    ProviderBilledStatus,
    ProviderOutcome,
)
from docprod.product.errors import ProductError
from docprod.product.failure import FailureCategory
from docprod.product.ids import new_id
from docprod.product.jobs import can_transition
from docprod.product.models import Asset, AssetVersion, GenerationAttempt, utcnow
from docprod.product.paid_ops import (
    CostCapExceeded,
    accounted_usd,
    assert_within_cap,
    existing_paid_attempt,
    must_not_resubmit,
    recover_submitted_without_resubmit,
    request_fingerprint,
)
from docprod.product.services import ProductService

LIVE_DISABLED = "Live paid provider execution is disabled until explicit canary enablement."


class RealGenerationWorker:
    """Product→engine worker. Dry-run by default. Never wraps paid calls in generic retries."""

    def __init__(
        self,
        service: ProductService,
        worker_id: str = "real",
        *,
        generation_mode: str = "real",
        allow_paid_generation: bool = False,
        allow_paid_apis: bool = False,
        dry_run: bool = True,
    ) -> None:
        if generation_mode != "real":
            raise ProductError("RealGenerationWorker requires GENERATION_MODE=real")
        if allow_paid_generation and not dry_run and not allow_paid_apis:
            raise ProductError("ALLOW_PAID_APIS must be true with ALLOW_PAID_GENERATION")
        self.service = service
        self.worker_id = worker_id
        self.lease = timedelta(seconds=30)
        self.generation_mode = generation_mode
        self.allow_paid_generation = allow_paid_generation
        self.allow_paid_apis = allow_paid_apis
        self.dry_run = dry_run
        self.paid_calls = 0

    def run_job(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        with log_scope(job_id=job_id, user_id=job.user_id, project_id=job.project_id):
            if job.status is JobStatus.COMPLETED:
                return
            if job.status is JobStatus.WAITING_FOR_PAYMENT:
                self.service.start_generation(job.user_id, job.id)
            recover_submitted_without_resubmit(self.service, job_id)
            self._heartbeat(job_id)
            kind = self.service.repo.jobs[job_id].kind
            if kind == "scene_image":
                self._run_scoped(job_id, image=True, video=False)
                return
            if kind == "scene_video":
                self._run_scoped(job_id, image=False, video=True)
                return
            if kind == "render":
                self._run_render_only(job_id)
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

    def _unit(
        self,
        job_id: str,
        label: str,
        *,
        completed: int | None = None,
        total: int | None = None,
    ) -> None:
        job = self.service.repo.jobs[job_id]
        current = job.progress.get(label)
        if not isinstance(current, dict):
            current = {"completed": 0, "total": 0}
        if total is not None:
            current["total"] = total
        if completed is not None:
            current["completed"] = completed
        job.progress[label] = current

    def _run_full(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
        try:
            spec = build_engine_spec(
                project,
                characters=self.service.repo.characters_for(project.id),
                references=[
                    ref
                    for ref in self.service.repo.references.values()
                    if ref.project_id == project.id
                ],
                hard_max_usd=job.provider_cost_cap,
                pricing=self.service.pricing,
            )
            if spec.estimated_provider_usd - 1e-9 > job.provider_cost_cap:
                self._fail(job_id, FailureCategory.INTERNAL_FAILURE, "PROVIDER_CAP_EXCEEDED")
                return
            if job.status is JobStatus.QUEUED:
                self._ensure_status(job_id, JobStatus.PLANNING)
            persist_engine_outline(self.service.repo, project, spec)
            versions = self.service.repo.active_versions(project.id)
            frozen = freeze_plan(project, spec, versions)
            job.progress["frozen_plan"] = frozen_plan_payload(frozen, spec)
            job.progress["analytics"] = {
                "stars_charged": self._stars_for_job(job_id),
                "estimated_provider_usd": frozen.estimated_provider_usd,
                "actual_known_provider_usd": 0.0,
                "scene_count": spec.scene_count,
                "video_seconds": 8 * sum(1 for scene in spec.scenes if scene.wants_video),
                "dry_run": self.dry_run,
            }
            self._unit(job_id, "story", completed=1, total=1)
            self._unit(job_id, "scene_planning", completed=spec.scene_count, total=spec.scene_count)
            self._ensure_status(job_id, JobStatus.GENERATING_SCRIPT)
            self._paid_step(
                job_id,
                item_type=PlanItemType.SCRIPT,
                provider=FIRST_CANARY_PROVIDERS["script"],
                model=FIRST_CANARY_PROVIDERS["script_model"],
                usd=next(
                    item.estimated_provider_usd
                    for item in spec.frozen_items
                    if item.type is PlanItemType.SCRIPT
                ),
                extra={"prompt": project.prompt},
            )
            self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
            scenes = self.service.repo.scenes_for(project.id)
            self._unit(job_id, "images", completed=0, total=len(scenes))
            for index, scene in enumerate(scenes):
                if scene.locked:
                    continue
                spec_scene = spec.scenes[index]
                version = self.service._active_version(scene)
                if version.image_asset_version_id and not version.image_stale:
                    self._bump(job_id, "images")
                    continue
                self._paid_step(
                    job_id,
                    item_type=PlanItemType.STILL,
                    provider=FIRST_CANARY_PROVIDERS["image"],
                    model=spec_scene.image_model,
                    usd=0.05,
                    scene_id=scene.id,
                    extra={"visual": spec_scene.visual_prompt, "refs": spec_scene.character_ids},
                )
                self._attach(
                    job.user_id,
                    scene.id,
                    kind=AssetKind.IMAGE,
                    data=b"dry-run-still",
                    mime="image/jpeg",
                    model=spec_scene.image_model,
                    provider=FIRST_CANARY_PROVIDERS["image"],
                )
                self._bump(job_id, "images")
                self._heartbeat(job_id)
            self._ensure_status(job_id, JobStatus.GENERATING_VIDEO)
            video_targets = [s for s in spec.scenes if s.wants_video]
            self._unit(job_id, "video", completed=0, total=len(video_targets))
            for index, scene in enumerate(scenes):
                spec_scene = spec.scenes[index]
                if not spec_scene.wants_video:
                    continue
                version = self.service._active_version(scene)
                if version.video_asset_version_id and not version.video_stale:
                    self._bump(job_id, "video")
                    continue
                self._paid_step(
                    job_id,
                    item_type=PlanItemType.VIDEO,
                    provider=FIRST_CANARY_PROVIDERS["video"],
                    model=spec_scene.video_model,
                    usd=0.40,
                    scene_id=scene.id,
                    extra={"duration": 8, "remote": True},
                    remote=True,
                )
                self._attach(
                    job.user_id,
                    scene.id,
                    kind=AssetKind.VIDEO,
                    data=b"dry-run-clip",
                    mime="video/mp4",
                    model=spec_scene.video_model,
                    provider=FIRST_CANARY_PROVIDERS["video"],
                )
                self._bump(job_id, "video")
                self._heartbeat(job_id)
            self._ensure_status(job_id, JobStatus.GENERATING_AUDIO)
            self._unit(job_id, "voice", completed=0, total=1)
            self._paid_step(
                job_id,
                item_type=PlanItemType.TTS,
                provider=FIRST_CANARY_PROVIDERS["tts"],
                model=FIRST_CANARY_PROVIDERS["tts_model"],
                usd=0.03,
                extra={"language": project.language},
            )
            self._unit(job_id, "voice", completed=1, total=1)
            self._unit(job_id, "audio", completed=1, total=1)
            self._ensure_status(job_id, JobStatus.RENDERING)
            self._run_render_only(job_id)
        except CostCapExceeded:
            self._fail(job_id, FailureCategory.INTERNAL_FAILURE, "PROVIDER_CAP_EXCEEDED")
        except ProductError:
            self._fail(job_id, FailureCategory.INTERNAL_FAILURE, "INTERNAL_FAILURE")

    def _run_scoped(self, job_id: str, *, image: bool, video: bool) -> None:
        job = self.service.repo.jobs[job_id]
        scene = self.service.repo.scenes[job.target_scene_id or ""]
        others = {
            other.id: self.service._active_version(other).id
            for other in self.service.repo.scenes_for(job.project_id)
            if other.id != scene.id
        }
        if image:
            self._attach(
                job.user_id,
                scene.id,
                kind=AssetKind.IMAGE,
                data=b"dry-run-still",
                mime="image/jpeg",
                model="gpt-image-2.5-flare",
                provider="openai",
            )
            self._unit(job_id, "images", completed=1, total=1)
        if video:
            self._attach(
                job.user_id,
                scene.id,
                kind=AssetKind.VIDEO,
                data=b"dry-run-clip",
                mime="video/mp4",
                model="veo-3.1-lite-generate-preview",
                provider="google",
            )
            self._unit(job_id, "video", completed=1, total=1)
        for other_id, version_id in others.items():
            other = self.service.repo.scenes[other_id]
            assert other.active_version_id == version_id
        self._complete_job(job_id, data=b"dry-run-scoped")

    def _run_render_only(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        self._unit(job_id, "render", completed=0, total=1)
        self._unit(job_id, "upload", completed=0, total=1)
        started = utcnow()
        data = b"dry-run-final-mp4"
        self._complete_job(job_id, data=data)
        analytics = job.progress.setdefault("analytics", {})
        analytics["render_duration_ms"] = int((utcnow() - started).total_seconds() * 1000)
        analytics["generation_duration_ms"] = int(
            ((job.completed_at or utcnow()) - (job.started_at or utcnow())).total_seconds() * 1000
        )
        analytics["actual_known_provider_usd"] = accounted_usd(job, self.service.repo)
        self._unit(job_id, "render", completed=1, total=1)
        self._unit(job_id, "upload", completed=1, total=1)

    def _complete_job(self, job_id: str, *, data: bytes) -> None:
        job = self.service.repo.jobs[job_id]
        key = f"projects/{job.project_id}/renders/{new_id()}.mp4"
        self.service.storage.put_bytes(key, data, content_type="video/mp4")
        asset = Asset(project_id=job.project_id, kind=AssetKind.RENDER)
        self.service.repo.assets[asset.id] = asset
        version = AssetVersion(
            asset_id=asset.id,
            storage_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            model="ffmpeg",
            provider="ffmpeg",
            mime="video/mp4",
            byte_size=len(data),
        )
        self.service.repo.asset_versions[version.id] = version
        job.progress["final_asset_version_id"] = version.id
        job = self.service.repo.jobs[job_id]
        for target in (
            JobStatus.PLANNING,
            JobStatus.GENERATING_SCRIPT,
            JobStatus.GENERATING_IMAGES,
            JobStatus.GENERATING_AUDIO,
            JobStatus.RENDERING,
        ):
            job = self.service.repo.jobs[job_id]
            if job.status is JobStatus.RENDERING:
                break
            if can_transition(job.status, target):
                self.service.advance_job(job_id, target)
        render = self.service.complete_job(job_id, storage_key=key)
        render.asset_version_id = version.id
        self._heartbeat(job_id)

    def _attach(
        self,
        user_id: str,
        scene_id: str,
        *,
        kind: AssetKind,
        data: bytes,
        mime: str,
        model: str,
        provider: str,
    ) -> AssetVersion:
        scene = self.service.repo.scenes[scene_id]
        asset = Asset(project_id=scene.project_id, scene_id=scene_id, kind=kind)
        self.service.repo.assets[asset.id] = asset
        key = f"projects/{scene.project_id}/scenes/{scene_id}/{kind.value}/{new_id()}"
        self.service.storage.put_bytes(key, data, content_type=mime)
        version = AssetVersion(
            asset_id=asset.id,
            storage_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            model=model,
            provider=provider,
            mime=mime,
            byte_size=len(data),
        )
        self.service.repo.asset_versions[version.id] = version
        scene_version = self.service._active_version(scene)
        if kind is AssetKind.IMAGE:
            scene_version.image_asset_version_id = version.id
            scene_version.image_stale = False
        if kind is AssetKind.VIDEO:
            scene_version.video_asset_version_id = version.id
            scene_version.video_stale = False
        return version

    def _paid_step(
        self,
        job_id: str,
        *,
        item_type: PlanItemType,
        provider: str,
        model: str,
        usd: float,
        scene_id: str | None = None,
        extra: dict | None = None,
        remote: bool = False,
    ) -> GenerationAttempt:
        job = self.service.repo.jobs[job_id]
        fingerprint = request_fingerprint(
            provider=provider,
            model=model,
            item_type=item_type,
            scene_id=scene_id,
            extra=extra,
        )
        existing = existing_paid_attempt(self.service.repo, job_id, fingerprint)
        if existing and must_not_resubmit(existing):
            if existing.status is AttemptStatus.RECOVERING_REMOTE:
                existing.status = AttemptStatus.SUCCEEDED
                existing.provider_outcome = ProviderOutcome.SUCCEEDED
                existing.completed_at = self.service.clock()
                existing.updated_at = self.service.clock()
            return existing
        spent = accounted_usd(job, self.service.repo)
        assert_within_cap(job, usd, spent=spent)
        if not self.dry_run:
            if not (self.allow_paid_generation and self.allow_paid_apis):
                raise ProductError("paid generation is not enabled")
            raise ProductError(LIVE_DISABLED)
        remote_id = f"dry-{fingerprint[:12]}" if remote else None
        status = AttemptStatus.SUBMITTED if remote else AttemptStatus.SUCCEEDED
        attempt = self.service.record_attempt(
            job_id,
            item_type=item_type,
            provider=provider,
            model=model,
            outcome=ProviderOutcome.SUCCEEDED,
            billed=ProviderBilledStatus.UNKNOWN,
            scene_id=scene_id,
            status=status,
            request_hash=fingerprint,
            remote_operation_id=remote_id,
            estimated_provider_cost=usd,
        )
        if remote:
            attempt.status = AttemptStatus.SUCCEEDED
            attempt.completed_at = self.service.clock()
            attempt.updated_at = self.service.clock()
        return attempt

    def _bump(self, job_id: str, label: str) -> None:
        job = self.service.repo.jobs[job_id]
        unit = job.progress.setdefault(label, {"completed": 0, "total": 0})
        unit["completed"] = int(unit.get("completed", 0)) + 1

    def _stars_for_job(self, job_id: str) -> int:
        job = self.service.repo.jobs[job_id]
        if not job.quote_id:
            return 0
        quote = self.service.repo.quotes.get(job.quote_id)
        return quote.stars if quote else 0

    def _fail(self, job_id: str, category: FailureCategory, code: str) -> None:
        self.service.fail_job(
            job_id,
            public_message="Generation failed.",
            error_code=code,
        )
        job = self.service.repo.jobs[job_id]
        job.progress["failure_category"] = category.value
