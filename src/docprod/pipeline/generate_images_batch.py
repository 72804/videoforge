from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from docprod.config import Settings, get_settings
from docprod.exceptions import MaxPaidRequestsExceededError, PaidApiNotConfirmedError
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.generate_image_stage import (
    IMAGE_STRATEGIES,
    execute_generate_image,
    load_or_create_visual_bible,
    should_skip_paid_generation,
)
from docprod.planning.visual_bible import next_protagonist_memory
from docprod.providers.image_config import (
    ImageBatchManifest,
    ImageBatchSceneRecord,
    ImageGenerationConfig,
)
from docprod.providers.image_prompt import build_documentary_image_prompt
from docprod.providers.image_review import load_review
from docprod.providers.openai_image import OpenAIImageProvider, image_request_hash
from docprod.storage.json_store import save_model
from docprod.storage.paths import ProjectPaths

ProgressFn = Callable[[str], None]

MAX_PAID_WORKERS = 2


@dataclass
class PlannedImageJob:
    scene: Scene
    action: str
    skip_reason: str | None
    prompt: str
    request_hash: str
    include_protagonist: bool
    previous_had_protagonist: bool


def plan_image_batch(
    paths: ProjectPaths,
    plan: ScenePlan,
    *,
    settings: Settings | None = None,
    force_scene_ids: Sequence[str] = (),
) -> tuple[list[PlannedImageJob], ImageGenerationConfig]:
    cfg = settings or get_settings()
    image_cfg = ImageGenerationConfig.from_settings(cfg)
    bible = load_or_create_visual_bible(paths, plan)
    force_ids = set(force_scene_ids)
    jobs: list[PlannedImageJob] = []
    previous_had = False
    for scene in plan.scenes:
        include, next_had = next_protagonist_memory(scene, bible, previous_had)
        if scene.asset_strategy in IMAGE_STRATEGIES:
            prompt = build_documentary_image_prompt(
                scene, bible=bible, include_protagonist=include
            )
            request_hash = image_request_hash(
                prompt=prompt, config=image_cfg, seed=scene.generation.seed
            )
            force = scene.id in force_ids
            skip, reason, _existing = should_skip_paid_generation(
                paths, scene, request_hash=request_hash, force=force
            )
            jobs.append(
                PlannedImageJob(
                    scene=scene,
                    action="SKIP" if skip else "GENERATE",
                    skip_reason=reason,
                    prompt=prompt,
                    request_hash=request_hash,
                    include_protagonist=include,
                    previous_had_protagonist=previous_had,
                )
            )
        previous_had = next_had
    return jobs, image_cfg


def execute_generate_images(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    confirm_paid: bool,
    max_paid_requests: int,
    workers: int = 1,
    force_scene_ids: Sequence[str] = (),
    settings: Settings | None = None,
    provider: OpenAIImageProvider | None = None,
    progress: ProgressFn | None = None,
    write_manifest: bool = True,
) -> ImageBatchManifest:
    if max_paid_requests < 0:
        raise ValueError("max_paid_requests must be >= 0")
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if workers > MAX_PAID_WORKERS:
        workers = MAX_PAID_WORKERS
    jobs, image_cfg = plan_image_batch(
        paths, plan, settings=settings, force_scene_ids=force_scene_ids
    )
    paid = sum(1 for job in jobs if job.action == "GENERATE")
    if progress:
        progress("IMAGE GENERATION PLAN")
        for job in jobs:
            extra = f" ({job.skip_reason})" if job.skip_reason else ""
            progress(
                f"{job.scene.id}  {job.scene.asset_strategy.value}  {job.action}{extra}"
            )
        progress(f"New paid requests: {paid}")
        progress(f"Existing/skipped: {len(jobs) - paid}")
    if paid > max_paid_requests:
        raise MaxPaidRequestsExceededError(
            f"Batch would make {paid} paid image requests, exceeding "
            f"--max-paid-requests {max_paid_requests}. Aborting before any API call."
        )
    if paid and not confirm_paid:
        raise PaidApiNotConfirmedError(
            "Paid image batch requires --confirm-paid in addition to ALLOW_PAID_APIS=true."
        )

    bible = load_or_create_visual_bible(paths, plan)
    records: list[ImageBatchSceneRecord] = []
    generated = skipped = failed = 0
    for job in jobs:
        if job.action == "SKIP":
            skipped += 1
            review = load_review(paths, job.scene.id)
            existing_meta = paths.scene_image_meta(job.scene.id)
            sha = None
            out = None
            prompt = job.prompt
            elapsed = None
            usage = None
            model = image_cfg.model
            if existing_meta.is_file():
                from docprod.pipeline.generate_image_stage import _load_success_manifest

                existing = _load_success_manifest(existing_meta)
                if existing is not None:
                    sha = existing.output_sha256
                    out = existing.output_path
                    prompt = existing.prompt
                    elapsed = existing.elapsed_seconds
                    usage = existing.usage
                    model = existing.model
            records.append(
                ImageBatchSceneRecord(
                    scene_id=job.scene.id,
                    strategy=job.scene.asset_strategy.value,
                    action="SKIP",
                    status="skipped",
                    provider=image_cfg.provider,
                    model=model,
                    prompt=prompt,
                    size=image_cfg.size,
                    quality=image_cfg.quality,
                    request_hash=job.request_hash,
                    output_path=out,
                    output_sha256=sha,
                    elapsed_seconds=elapsed,
                    usage=usage,
                    review_state=review.review_state if review else job.skip_reason,
                    skip_reason=job.skip_reason,
                )
            )
            continue
        review = load_review(paths, job.scene.id)
        try:
            manifest = execute_generate_image(
                paths,
                plan=plan,
                scene_id=job.scene.id,
                confirm_paid=confirm_paid,
                force=job.scene.id in set(force_scene_ids),
                settings=settings,
                provider=provider,
                bible=bible,
                previous_had_protagonist=job.previous_had_protagonist,
                progress=progress,
            )
            generated += 1
            rec_review = load_review(paths, job.scene.id)
            records.append(
                ImageBatchSceneRecord(
                    scene_id=job.scene.id,
                    strategy=job.scene.asset_strategy.value,
                    action="GENERATE",
                    status="generated",
                    provider=manifest.provider,
                    model=manifest.model,
                    prompt=manifest.prompt,
                    size=manifest.size,
                    quality=manifest.quality,
                    request_hash=manifest.request_hash,
                    output_path=manifest.output_path,
                    output_sha256=manifest.output_sha256,
                    elapsed_seconds=manifest.elapsed_seconds,
                    usage=manifest.usage,
                    review_state=rec_review.review_state if rec_review else "generated",
                )
            )
        except Exception as exc:
            failed += 1
            detail = str(exc)
            if "sk-" in detail.lower() or "authorization" in detail.lower():
                detail = "OpenAI request failed (details omitted to avoid leaking secrets)"
            if progress:
                progress(f"FAILED {job.scene.id}: {detail}")
            records.append(
                ImageBatchSceneRecord(
                    scene_id=job.scene.id,
                    strategy=job.scene.asset_strategy.value,
                    action="GENERATE",
                    status="failed",
                    provider=image_cfg.provider,
                    model=image_cfg.model,
                    prompt=job.prompt,
                    size=image_cfg.size,
                    quality=image_cfg.quality,
                    request_hash=job.request_hash,
                    review_state=review.review_state if review else None,
                    error=detail,
                )
            )
    manifest = ImageBatchManifest(
        project_id=plan.project_id,
        provider=image_cfg.provider,
        model=image_cfg.model,
        size=image_cfg.size,
        quality=image_cfg.quality,
        planned_paid_requests=paid,
        max_paid_requests=max_paid_requests,
        generated=generated,
        skipped=skipped,
        failed=failed,
        scenes=records,
    )
    if write_manifest:
        save_model(paths.image_batch_manifest(), manifest)
    return manifest
