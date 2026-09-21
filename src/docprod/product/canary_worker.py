from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docprod.product.canary_adapters import AdapterResult, CanaryAdapters
from docprod.product.canary_cost import (
    CHARACTER_REF_SCENE_ID,
    image_cost_from_usage,
    reserve_image_usd,
    reserve_tts_usd,
    text_cost_from_usage,
    tts_cost_from_usage,
    veo_cost,
)
from docprod.product.canary_render import render_canary_preview
from docprod.product.engine_bridge import (
    FIRST_CANARY_PROVIDERS,
    EngineProjectSpec,
    EngineSceneSpec,
    build_engine_spec,
    freeze_plan,
    persist_engine_outline,
)
from docprod.product.enums import (
    AssetKind,
    AttemptStatus,
    JobStatus,
    PlanItemType,
    ProviderBilledStatus,
    ProviderOutcome,
    ReferenceMode,
)
from docprod.product.errors import ProductError
from docprod.product.failure import FailureCategory
from docprod.product.models import CharacterReference
from docprod.product.paid_ops import (
    accounted_usd,
    assert_within_cap,
    existing_paid_attempt,
    must_not_resubmit,
    request_fingerprint,
)
from docprod.product.real_worker import LIVE_DISABLED, RealGenerationWorker
from docprod.storage.hashing import file_sha256
from docprod.storage.paths import default_projects_root

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_canary_script(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1]
    match = _JSON_BLOCK.search(raw)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def clamp_script_beats(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        return [], 24.0
    beats: list[dict[str, Any]] = []
    video_used = False
    for row in scenes[:5]:
        if not isinstance(row, dict):
            continue
        wants = bool(row.get("wants_video")) and not video_used
        if wants:
            video_used = True
        duration = float(row.get("duration_seconds") or 8)
        duration = min(12.0, max(4.0, duration))
        beats.append(
            {
                "narration": str(row.get("narration") or "").strip() or "Beat.",
                "visual": str(row.get("visual") or "").strip() or "Cinematic still.",
                "motion": str(row.get("motion") or "subtle camera drift"),
                "duration_seconds": duration,
                "wants_video": wants,
            }
        )
    if len(beats) < 2:
        return [], 24.0
    beats = beats[:5]
    total = sum(item["duration_seconds"] for item in beats)
    if total < 15 or total > 30:
        scale = 24.0 / total
        for item in beats:
            item["duration_seconds"] = round(item["duration_seconds"] * scale, 3)
        total = sum(item["duration_seconds"] for item in beats)
    return beats, round(total, 3)


class LocalCanaryWorker(RealGenerationWorker):
    """Live local-canary worker. Non-canary jobs still hit LIVE_DISABLED."""

    def __init__(
        self,
        service,
        *,
        adapters: CanaryAdapters,
        work_root: Path,
        final_path: Path,
        slug: str,
        use_ffmpeg: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(service, **kwargs)
        self.adapters = adapters
        self.work_root = work_root
        self.final_path = final_path
        self.slug = slug
        self.use_ffmpeg = use_ffmpeg
        self._files: dict[str, Path] = {}

    def _is_canary_job(self, job_id: str) -> bool:
        job = self.service.repo.jobs[job_id]
        flagged = bool(job.progress.get("local_canary"))
        return flagged and job.progress.get("canary_slug") == self.slug

    def _run_full(self, job_id: str) -> None:
        if not self._is_canary_job(job_id):
            super()._run_full(job_id)
            return
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
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
        self._freeze(job_id, spec)
        self._ensure_status(job_id, JobStatus.GENERATING_SCRIPT)
        script_item = next(item for item in spec.frozen_items if item.type is PlanItemType.SCRIPT)
        script_result = self._ledger_call(
            job_id,
            item_type=PlanItemType.SCRIPT,
            provider=FIRST_CANARY_PROVIDERS["script"],
            model=script_item.model,
            usd=script_item.estimated_provider_usd,
            extra={"prompt": project.prompt},
            runner=lambda: self.adapters.generate_script(project.prompt),
            cost_from_usage=text_cost_from_usage,
        )
        spec = self._apply_script(job_id, spec, script_result)
        self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
        self._generate_identity_and_stills(job_id, spec)
        self._ensure_status(job_id, JobStatus.GENERATING_VIDEO)
        self._generate_video(job_id, spec)
        self._ensure_status(job_id, JobStatus.GENERATING_AUDIO)
        narration = " ".join(scene.narration for scene in spec.scenes)
        self._ledger_call(
            job_id,
            item_type=PlanItemType.TTS,
            provider=FIRST_CANARY_PROVIDERS["tts"],
            model=FIRST_CANARY_PROVIDERS["tts_model"],
            usd=reserve_tts_usd(),
            extra={"language": project.language, "chars": len(narration)},
            runner=lambda: self.adapters.generate_tts(narration),
            cost_from_usage=tts_cost_from_usage,
            file_key="tts",
            suffix=".wav",
        )
        self._ensure_status(job_id, JobStatus.RENDERING)
        self._render_final(job_id, spec)

    def _freeze(self, job_id: str, spec: EngineProjectSpec) -> None:
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
        versions = self.service.repo.active_versions(project.id)
        freeze_plan(project, spec, versions)
        job.progress["frozen_plan"] = {
            "scene_count": spec.scene_count,
            "duration_seconds": spec.duration_seconds,
            "reserved_provider_usd": spec.estimated_provider_usd,
            "items": [
                {
                    "type": item.type.value,
                    "model": item.model,
                    "reserved_provider_usd": item.estimated_provider_usd,
                    "scene_id": item.scene_id,
                }
                for item in spec.frozen_items
            ],
        }
        job.reserved_provider_cost = spec.estimated_provider_usd
        self._unit(job_id, "story", completed=1, total=1)
        self._unit(job_id, "scene_planning", completed=spec.scene_count, total=spec.scene_count)

    def _apply_script(
        self, job_id: str, spec: EngineProjectSpec, result: AdapterResult | None
    ) -> EngineProjectSpec:
        if result is None or not result.text:
            return spec
        parsed = parse_canary_script(result.text)
        if parsed is None:
            return spec
        beats, total = clamp_script_beats(parsed)
        if not beats:
            return spec
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
        scenes: list[EngineSceneSpec] = []
        remaining_video = 1
        for index, beat in enumerate(beats):
            template = spec.scenes[min(index, len(spec.scenes) - 1)]
            wants = bool(beat["wants_video"]) and remaining_video > 0
            if wants:
                remaining_video -= 1
            scenes.append(
                EngineSceneSpec(
                    order_index=index,
                    visual_prompt=beat["visual"],
                    motion_prompt=beat["motion"],
                    narration=beat["narration"],
                    duration_seconds=beat["duration_seconds"],
                    production_class=template.production_class,
                    image_model=template.image_model,
                    video_model=(
                        FIRST_CANARY_PROVIDERS["video_model"] if wants else "local-camera"
                    ),
                    wants_video=wants,
                    character_ids=template.character_ids,
                )
            )
        rebuilt = build_engine_spec(
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
        updated = EngineProjectSpec(
            content_kind=rebuilt.content_kind,
            duration_seconds=total,
            scene_count=len(scenes),
            quality_profile=rebuilt.quality_profile,
            aspect_ratio=rebuilt.aspect_ratio,
            language=rebuilt.language,
            characters=rebuilt.characters,
            scenes=tuple(scenes),
            frozen_items=rebuilt.frozen_items,
            estimated_provider_usd=rebuilt.estimated_provider_usd,
            hard_max_usd=rebuilt.hard_max_usd,
        )
        persist_engine_outline(self.service.repo, project, updated, replace=True)
        self._freeze(job_id, updated)
        return updated

    def _generate_identity_and_stills(self, job_id: str, spec: EngineProjectSpec) -> None:
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
        characters = self.service.repo.characters_for(project.id)
        scenes = self.service.repo.scenes_for(project.id)
        extra_ref = 1 if characters else 0
        self._unit(job_id, "images", completed=0, total=len(scenes) + extra_ref)
        ref_paths: list[Path] = []
        if characters:
            character = characters[0]
            prompt = (
                f"Photoreal cinematic portrait of {character.name}. "
                f"{character.description} Neutral basement lighting, 9:16, single person."
            )
            result = self._ledger_call(
                job_id,
                item_type=PlanItemType.STILL,
                provider=FIRST_CANARY_PROVIDERS["image"],
                model=FIRST_CANARY_PROVIDERS["image_model"],
                usd=reserve_image_usd(with_reference=False),
                scene_id=CHARACTER_REF_SCENE_ID,
                extra={
                    "kind": "character_reference",
                    "size": "1024x1536",
                    "quality": "medium",
                },
                runner=lambda: self.adapters.generate_image(prompt),
                cost_from_usage=image_cost_from_usage,
                file_key="character_ref",
                suffix=".jpg",
            )
            if result is not None:
                path = self._files["character_ref"]
                record = CharacterReference(
                    character_id=character.id,
                    project_id=project.id,
                    storage_key=str(path),
                    sha256=file_sha256(path),
                    mode=ReferenceMode.AUTO_GENERATED,
                    primary=True,
                    role="primary",
                    mime="image/jpeg",
                )
                self.service.repo.references[record.id] = record
                character.primary_reference_id = record.id
                character.locked_identity = True
                ref_paths = [path]
            self._bump(job_id, "images")
        for index, scene in enumerate(scenes):
            spec_scene = spec.scenes[index]
            version = self.service._active_version(scene)
            if version.image_asset_version_id and not version.image_stale:
                self._bump(job_id, "images")
                continue
            result = self._ledger_call(
                job_id,
                item_type=PlanItemType.STILL,
                provider=FIRST_CANARY_PROVIDERS["image"],
                model=spec_scene.image_model,
                usd=reserve_image_usd(with_reference=bool(ref_paths)),
                scene_id=scene.id,
                extra={
                    "visual": spec_scene.visual_prompt,
                    "size": "1024x1536",
                    "quality": "medium",
                    "refs": spec_scene.character_ids,
                },
                runner=lambda prompt=spec_scene.visual_prompt: self.adapters.generate_image(
                    prompt, reference_images=ref_paths or None
                ),
                cost_from_usage=image_cost_from_usage,
                file_key=f"still_{index}",
                suffix=".jpg",
            )
            if result is not None:
                self._attach(
                    job.user_id,
                    scene.id,
                    kind=AssetKind.IMAGE,
                    data=result.data,
                    mime="image/jpeg",
                    model=spec_scene.image_model,
                    provider=FIRST_CANARY_PROVIDERS["image"],
                )
            self._bump(job_id, "images")

    def _generate_video(self, job_id: str, spec: EngineProjectSpec) -> None:
        job = self.service.repo.jobs[job_id]
        scenes = self.service.repo.scenes_for(job.project_id)
        targets = [scene for scene in spec.scenes if scene.wants_video]
        self._unit(job_id, "video", completed=0, total=len(targets))
        for index, scene in enumerate(scenes):
            spec_scene = spec.scenes[index]
            if not spec_scene.wants_video:
                continue
            still = self._files.get(f"still_{index}")
            if still is None:
                raise ProductError("Veo scene is missing its generated still")

            def _run(path: Path = still, prompt: str = spec_scene.motion_prompt) -> AdapterResult:
                return self.adapters.generate_video(prompt, path, scene_id=scene.id)

            def _recover(
                path: Path = still, prompt: str = spec_scene.motion_prompt
            ) -> AdapterResult:
                return self.adapters.recover_video(prompt, path, scene_id=scene.id)

            result = self._ledger_call(
                job_id,
                item_type=PlanItemType.VIDEO,
                provider=FIRST_CANARY_PROVIDERS["video"],
                model=spec_scene.video_model,
                usd=veo_cost(8),
                scene_id=scene.id,
                extra={"duration": 8, "resolution": "720p", "remote": True},
                remote=True,
                runner=_run,
                recover=_recover,
                file_key=f"video_{index}",
                suffix=".mp4",
            )
            if result is not None:
                self._attach(
                    job.user_id,
                    scene.id,
                    kind=AssetKind.VIDEO,
                    data=result.data,
                    mime="video/mp4",
                    model=spec_scene.video_model,
                    provider=FIRST_CANARY_PROVIDERS["video"],
                )
            self._bump(job_id, "video")

    def _render_final(self, job_id: str, spec: EngineProjectSpec) -> None:
        job = self.service.repo.jobs[job_id]
        segments: list[tuple[str, Path, float]] = []
        for index, scene in enumerate(spec.scenes):
            if scene.wants_video and f"video_{index}" in self._files:
                segments.append(("video", self._files[f"video_{index}"], scene.duration_seconds))
            else:
                still = self._files.get(f"still_{index}")
                if still is None:
                    raise ProductError("missing still for render")
                segments.append(("still", still, scene.duration_seconds))
        tts = self._files.get("tts")
        narration = " ".join(scene.narration for scene in spec.scenes)
        if self.dry_run or not self.use_ffmpeg:
            data = b"dry-run-final-mp4"
            self.final_path.parent.mkdir(parents=True, exist_ok=True)
            self.final_path.write_bytes(data)
        else:
            render_canary_preview(
                segments=segments,
                tts_wav=tts,
                narration=narration,
                dest=self.final_path,
                work=self.work_root / "render",
            )
            data = self.final_path.read_bytes()
        self._complete_job(job_id, data=data)
        job.progress["final_output"] = str(self.final_path)
        job.progress["analytics"] = {
            "actual_known_provider_usd": accounted_usd(job, self.service.repo),
            "reserved_provider_usd": job.reserved_provider_cost,
            "dry_run": self.dry_run,
        }

    def _ledger_call(
        self,
        job_id: str,
        *,
        item_type: PlanItemType,
        provider: str,
        model: str,
        usd: float,
        extra: dict[str, Any] | None = None,
        scene_id: str | None = None,
        remote: bool = False,
        runner,
        recover=None,
        cost_from_usage=None,
        file_key: str | None = None,
        suffix: str = "",
    ) -> AdapterResult | None:
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
            if existing.status is AttemptStatus.SUCCEEDED:
                return None
            if recover is None:
                raise ProductError("remote paid operation is uncertain; stopping without resubmit")
            result = recover()
            existing.status = AttemptStatus.SUCCEEDED
            existing.provider_outcome = ProviderOutcome.SUCCEEDED
            existing.completed_at = self.service.clock()
            existing.updated_at = self.service.clock()
            self._store_file(file_key, suffix, result)
            return result
        spent = accounted_usd(job, self.service.repo)
        if existing is None or existing.status is AttemptStatus.PENDING:
            assert_within_cap(job, usd, spent=spent)
        if not self.dry_run:
            if not (self.allow_paid_generation and self.allow_paid_apis):
                raise ProductError("paid generation is not enabled")
            if not self._is_canary_job(job_id):
                raise ProductError(LIVE_DISABLED)
        attempt = existing
        if attempt is None:
            attempt = self.service.record_attempt(
                job_id,
                item_type=item_type,
                provider=provider,
                model=model,
                outcome=ProviderOutcome.SKIPPED,
                billed=ProviderBilledStatus.UNKNOWN,
                scene_id=scene_id,
                status=AttemptStatus.PENDING,
                request_hash=fingerprint,
                estimated_provider_cost=usd,
            )
        if self.dry_run:
            attempt.status = AttemptStatus.SUCCEEDED
            attempt.provider_outcome = ProviderOutcome.SUCCEEDED
            attempt.completed_at = self.service.clock()
            placeholder = b"dry-run"
            if file_key:
                path = self.work_root / f"{file_key}{suffix or '.bin'}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(placeholder)
                self._files[file_key] = path
            return AdapterResult(data=placeholder, text="{}")
        self.paid_calls += 1
        if remote:
            attempt.status = AttemptStatus.SUBMITTED
            attempt.updated_at = self.service.clock()
            self._persist()
        result = runner()
        if remote:
            attempt.remote_operation_id = result.remote_operation_id or attempt.remote_operation_id
            self._persist()
        actual = cost_from_usage(result.usage) if cost_from_usage is not None else None
        attempt.actual_provider_cost = actual
        attempt.status = AttemptStatus.SUCCEEDED
        attempt.provider_outcome = ProviderOutcome.SUCCEEDED
        attempt.completed_at = self.service.clock()
        attempt.updated_at = self.service.clock()
        self._store_file(file_key, suffix, result)
        return result

    def _store_file(self, file_key: str | None, suffix: str, result: AdapterResult) -> None:
        if not file_key:
            return
        path = self.work_root / f"{file_key}{suffix or '.bin'}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.data)
        self._files[file_key] = path


def default_canary_work_root() -> Path:
    return default_projects_root() / "videoforge_local_canary" / "artifacts" / "work"
