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
from docprod.product.canary_ledger import is_real_jpeg, is_real_media
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
    CostCapExceeded,
    accounted_usd,
    assert_within_cap,
    existing_paid_attempt,
    must_not_resubmit,
    request_fingerprint,
)
from docprod.product.persist import save_repository
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
        store_path: Path | None = None,
        canary_root: Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(service, **kwargs)
        self.adapters = adapters
        self.work_root = work_root
        self.final_path = final_path
        self.slug = slug
        self.use_ffmpeg = use_ffmpeg
        self.store_path = store_path
        self.canary_root = canary_root
        self._files: dict[str, Path] = {}

    def _persist(self) -> None:
        super()._persist()
        if self.store_path is not None:
            save_repository(self.store_path, self.service.repo)

    def _hydrate_artifacts(self) -> None:
        mapping = {
            "character_ref": (".jpg", is_real_jpeg),
            "tts": (".wav", is_real_media),
        }
        for key, (suffix, check) in mapping.items():
            path = self.work_root / f"{key}{suffix}"
            if check(path):
                self._files[key] = path
        for index in range(16):
            path = self.work_root / f"still_{index}.jpg"
            if is_real_jpeg(path):
                self._files[f"still_{index}"] = path
            else:
                break
        for path in sorted(self.work_root.glob("video_*.mp4")):
            if is_real_media(path):
                self._files[path.stem] = path
        script = self.work_root / "script.json"
        if script.is_file():
            self._files["script"] = script

    def _discovered_ops(self) -> dict[str, dict[str, Any]]:
        from docprod.product.canary_ledger import discover_operations

        root = self.canary_root
        if root is None:
            root = self.work_root.parent.parent
        return discover_operations(root)

    def _discovered_veo(self) -> dict[str, Any]:
        return self._discovered_ops().get("veo") or {}

    def _account_existing(self, job_id: str) -> None:
        job = self.service.repo.jobs[job_id]
        if job.progress.get("resume_seeded"):
            return
        ops = self._discovered_ops()
        for name, row in ops.items():
            state = str(row.get("state") or "")
            if state in {"SUCCEEDED", "SUCCEEDED_RESPONSE_LOST"}:
                item = {
                    "script": PlanItemType.SCRIPT,
                    "character_ref": PlanItemType.STILL,
                    "tts": PlanItemType.TTS,
                    "veo": PlanItemType.VIDEO,
                }.get(name, PlanItemType.STILL if name.startswith("scene_still_") else None)
                if item is None or name == "render":
                    continue
                self.service.record_attempt(
                    job_id,
                    item_type=item,
                    provider=str(row.get("provider") or "unknown"),
                    model=str(row.get("model") or ""),
                    outcome=ProviderOutcome.SUCCEEDED,
                    billed=ProviderBilledStatus.UNKNOWN,
                    status=AttemptStatus.SUCCEEDED,
                    request_hash=request_fingerprint(
                        provider=str(row.get("provider") or "unknown"),
                        model=str(row.get("model") or ""),
                        item_type=item,
                        scene_id=None,
                        extra={"resume_seed": name},
                    ),
                    estimated_provider_cost=float(row.get("reserved_usd") or 0.0),
                    actual_provider_cost=row.get("actual_usd"),
                )
            elif name == "veo" and row.get("remote_operation_id"):
                self.service.record_attempt(
                    job_id,
                    item_type=PlanItemType.VIDEO,
                    provider="google",
                    model=str(row.get("model") or FIRST_CANARY_PROVIDERS["video_model"]),
                    outcome=ProviderOutcome.SKIPPED,
                    billed=ProviderBilledStatus.UNKNOWN,
                    status=AttemptStatus.SUBMITTED,
                    remote_operation_id=str(row["remote_operation_id"]),
                    request_hash=request_fingerprint(
                        provider="google",
                        model=str(row.get("model") or ""),
                        item_type=PlanItemType.VIDEO,
                        scene_id=None,
                        extra={"resume_seed": "veo"},
                    ),
                    estimated_provider_cost=float(row.get("reserved_usd") or 0.0),
                )
            elif name == "veo" and state == "UNCERTAIN":
                self.service.record_attempt(
                    job_id,
                    item_type=PlanItemType.VIDEO,
                    provider="google",
                    model=str(row.get("model") or FIRST_CANARY_PROVIDERS["video_model"]),
                    outcome=ProviderOutcome.FAILED,
                    billed=ProviderBilledStatus.UNKNOWN,
                    status=AttemptStatus.FAILED,
                    remote_operation_id="uncertain",
                    request_hash=request_fingerprint(
                        provider="google",
                        model=str(row.get("model") or ""),
                        item_type=PlanItemType.VIDEO,
                        scene_id=None,
                        extra={"resume_seed": "veo-uncertain"},
                    ),
                    estimated_provider_cost=float(row.get("reserved_usd") or 0.0),
                    safe_error_message="uncertain paid state from prior run",
                )
        job.progress["resume_seeded"] = True
        self._persist()

    def _is_canary_job(self, job_id: str) -> bool:
        job = self.service.repo.jobs[job_id]
        flagged = bool(job.progress.get("local_canary"))
        return flagged and job.progress.get("canary_slug") == self.slug

    def _run_full(self, job_id: str) -> None:
        if not self._is_canary_job(job_id):
            super()._run_full(job_id)
            return
        try:
            self._run_canary(job_id)
        except (ProductError, ValueError, CostCapExceeded) as exc:
            job = self.service.repo.jobs[job_id]
            job.progress["safe_error"] = str(exc)[:240]
            if job.status is not JobStatus.FAILED:
                self._fail(job_id, FailureCategory.INTERNAL_FAILURE, "INTERNAL_FAILURE")
        finally:
            self._persist()

    def _run_canary(self, job_id: str) -> None:
        self._hydrate_artifacts()
        self._account_existing(job_id)
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
        from docprod.product.canary_ledger import durable_downstream_spec

        durable = durable_downstream_spec(self.canary_root)
        stills_exist = any(key.startswith("still_") for key in self._files)
        if durable is not None:
            spec = self._apply_resume_spec(job_id, spec, durable)
        elif stills_exist:
            raise ProductError(
                "BLOCKED: paid script JSON missing and no durable resume spec; "
                "refusing to call script provider"
            )
        else:
            script_item = next(
                item for item in spec.frozen_items if item.type is PlanItemType.SCRIPT
            )
            script_result = self._ledger_call(
                job_id,
                item_type=PlanItemType.SCRIPT,
                provider=FIRST_CANARY_PROVIDERS["script"],
                model=script_item.model,
                usd=script_item.estimated_provider_usd,
                extra={"prompt": project.prompt},
                runner=lambda: self.adapters.generate_script(project.prompt),
                cost_from_usage=text_cost_from_usage,
                file_key="script",
                suffix=".json",
            )
            spec = self._apply_script(job_id, spec, script_result)
        self._trim_stills(spec)
        self._ensure_status(job_id, JobStatus.GENERATING_IMAGES)
        self._generate_identity_and_stills(job_id, spec)
        self._ensure_status(job_id, JobStatus.GENERATING_VIDEO)
        self._generate_video(job_id, spec)
        self._ensure_status(job_id, JobStatus.GENERATING_AUDIO)
        narration = " ".join(scene.narration for scene in spec.scenes)
        if "tts" not in self._files:
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

    def _trim_stills(self, spec: EngineProjectSpec) -> None:
        allowed = {f"still_{index}" for index in range(spec.scene_count)}
        for key in [item for item in self._files if item.startswith("still_")]:
            if key not in allowed:
                self._files.pop(key, None)

    def _apply_resume_spec(
        self, job_id: str, spec: EngineProjectSpec, durable: dict[str, Any]
    ) -> EngineProjectSpec:
        payload = durable.get("payload") if isinstance(durable, dict) else None
        if durable.get("kind") == "script.json" and isinstance(payload, dict):
            return self._apply_script(
                job_id,
                spec,
                AdapterResult(data=json.dumps(payload).encode(), text=json.dumps(payload)),
            )
        rows = payload.get("scenes") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) < 2:
            return spec
        job = self.service.repo.jobs[job_id]
        project = self.service.repo.projects[job.project_id]
        scenes: list[EngineSceneSpec] = []
        remaining_video = 1
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            template = spec.scenes[min(index, len(spec.scenes) - 1)]
            wants = bool(row.get("wants_video")) and remaining_video > 0
            if wants:
                remaining_video -= 1
            scenes.append(
                EngineSceneSpec(
                    order_index=index,
                    visual_prompt=str(row.get("visual_prompt") or template.visual_prompt),
                    motion_prompt=str(row.get("motion_prompt") or template.motion_prompt),
                    narration=str(row.get("narration") or template.narration),
                    duration_seconds=float(
                        row.get("duration_seconds") or template.duration_seconds
                    ),
                    production_class=template.production_class,
                    image_model=template.image_model,
                    video_model=(
                        FIRST_CANARY_PROVIDERS["video_model"] if wants else "local-camera"
                    ),
                    wants_video=wants,
                    character_ids=list(template.character_ids),
                )
            )
        if len(scenes) < 2:
            return spec
        updated = EngineProjectSpec(
            content_kind=spec.content_kind,
            duration_seconds=sum(scene.duration_seconds for scene in scenes),
            scene_count=len(scenes),
            quality_profile=spec.quality_profile,
            aspect_ratio=spec.aspect_ratio,
            language=spec.language,
            characters=spec.characters,
            scenes=tuple(scenes),
            frozen_items=spec.frozen_items,
            estimated_provider_usd=spec.estimated_provider_usd,
            hard_max_usd=spec.hard_max_usd,
        )
        persist_engine_outline(self.service.repo, project, updated, replace=True)
        self._freeze(job_id, updated)
        return updated

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
            existing = self._files.get("character_ref")
            if existing is not None:
                result = AdapterResult(data=existing.read_bytes())
            else:
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
            if result is not None and "character_ref" in self._files:
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
            file_key = f"still_{index}"
            if version.image_asset_version_id and not version.image_stale:
                self._bump(job_id, "images")
                continue
            if file_key in self._files:
                data = self._files[file_key].read_bytes()
                self._attach(
                    job.user_id,
                    scene.id,
                    kind=AssetKind.IMAGE,
                    data=data,
                    mime="image/jpeg",
                    model=spec_scene.image_model,
                    provider=FIRST_CANARY_PROVIDERS["image"],
                )
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
            if f"video_{index}" in self._files:
                self._bump(job_id, "video")
                continue
            veo_row = self._discovered_veo()
            remote_id = veo_row.get("remote_operation_id")
            if isinstance(remote_id, str) and remote_id.startswith("fake"):
                remote_id = None
            if veo_row.get("state") == "UNCERTAIN":
                raise ProductError("remote paid operation is uncertain; stopping without resubmit")
            if remote_id:

                def _recover_existing(
                    path: Path = still, prompt: str = spec_scene.motion_prompt
                ) -> AdapterResult:
                    return self.adapters.recover_video(prompt, path, scene_id=scene.id)

                result = _recover_existing()
                self._store_file(f"video_{index}", ".mp4", result)
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
                continue

            def _run(path: Path = still, prompt: str = spec_scene.motion_prompt) -> AdapterResult:
                return self.adapters.generate_video(prompt, path, scene_id=scene.id)

            def _recover(
                path: Path = still, prompt: str = spec_scene.motion_prompt
            ) -> AdapterResult:
                return self.adapters.recover_video(prompt, path, scene_id=scene.id)

            def _preflight(
                path: Path = still, prompt: str = spec_scene.motion_prompt
            ) -> None:
                self.adapters.preflight_video(prompt, path, scene_id=scene.id)

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
                preflight=_preflight,
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
        preflight=None,
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
        if existing and existing.status is AttemptStatus.FAILED_UNBILLED:
            existing.status = AttemptStatus.PENDING
        if existing and must_not_resubmit(existing):
            if existing.status is AttemptStatus.SUCCEEDED:
                return None
            if existing.remote_operation_id and recover is not None:
                result = recover()
                existing.status = AttemptStatus.SUCCEEDED
                existing.provider_outcome = ProviderOutcome.SUCCEEDED
                existing.completed_at = self.service.clock()
                existing.updated_at = self.service.clock()
                self._store_file(file_key, suffix, result)
                self._persist()
                return result
            raise ProductError("remote paid operation is uncertain; stopping without resubmit")
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
        attempt.status = AttemptStatus.PENDING
        attempt.updated_at = self.service.clock()
        self._persist()
        try:
            if preflight is not None:
                preflight()
        except Exception as exc:
            attempt.status = AttemptStatus.FAILED_UNBILLED
            attempt.provider_billed = ProviderBilledStatus.NOT_BILLED
            attempt.provider_outcome = ProviderOutcome.FAILED
            attempt.safe_error_message = str(exc)[:240]
            attempt.completed_at = self.service.clock()
            attempt.updated_at = self.service.clock()
            self._persist()
            raise
        if remote:
            attempt.status = AttemptStatus.SUBMITTED
            attempt.updated_at = self.service.clock()
            self._persist()
        try:
            result = runner()
        except Exception as exc:
            attempt.safe_error_message = str(exc)[:240]
            attempt.updated_at = self.service.clock()
            attempt.provider_outcome = ProviderOutcome.FAILED
            if remote:
                if not attempt.remote_operation_id:
                    attempt.provider_billed = ProviderBilledStatus.UNKNOWN
                self._persist()
                raise ProductError(
                    "remote paid operation is uncertain; stopping without resubmit"
                ) from exc
            attempt.status = AttemptStatus.FAILED_UNBILLED
            attempt.provider_billed = ProviderBilledStatus.NOT_BILLED
            attempt.completed_at = self.service.clock()
            self._persist()
            raise
        self.paid_calls += 1
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
        self._persist()
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
