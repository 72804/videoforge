from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docprod.audio.script import build_canonical_script
from docprod.audio.timeline import apply_runtime_timeline
from docprod.audio.tts_preflight import inspect_tts_input
from docprod.exceptions import TtsInputLimitError
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.generate_narration import generate_narration
from docprod.pipeline.inspect_assets import require_zero_placeholders
from docprod.pipeline.review_images import (
    generate_review_images,
    plan_review_image_jobs,
    write_paid_visuals_sheet,
)
from docprod.production import AssetPlan, AssetUnit
from docprod.production.balance import _apply_strategy
from docprod.production.info_graphics import convert_info_graphic_units
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.request_budget import ModelRequestBudget
from docprod.render.models import PreviewRenderProfile
from docprod.render.renderer import render_preview
from docprod.render.still import STOCK_STRATEGIES
from docprod.stock.downloader import normalize_stock_clip, pick_clip_start
from docprod.stock.models import StockSourceManifest
from docprod.storage.json_store import load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths


@dataclass
class ReviewDryRun:
    scene_count: int
    asset_unit_count: int
    strategy_counts: dict[str, int]
    paid_image_requests: int
    tts_requests: int
    whisper_requests: int
    video_model_requests: int
    image_model: str
    image_quality: str
    tts_model: str
    tts_voice: str
    tts_chars: int
    tts_tokens: int
    tts_within_limit: bool
    tts_reason: str
    output_paths: list[str] = field(default_factory=list)


def _stamp_units_on_scenes(plan: ScenePlan, asset_plan: AssetPlan) -> ScenePlan:
    by_scene: dict[str, AssetUnit] = {}
    for unit in asset_plan.units:
        for scene_id in unit.scene_ids:
            by_scene[scene_id] = unit
    scenes: list[Scene] = []
    for scene in plan.scenes:
        unit = by_scene[scene.id]
        scene = _apply_strategy(scene, unit.source_strategy, "asset_unit_stamp")
        meta = dict(scene.metadata)
        meta["asset_unit_id"] = unit.asset_unit_id
        if unit.source_path:
            meta["source_path"] = unit.source_path
        if unit.source_strategy is AssetStrategy.ai_image_to_video:
            meta["planned_strategy"] = "ai_image_to_video"
            meta["runtime_preview_strategy"] = "ai_keyframe_preview"
        effect = scene.effect
        if unit.source_strategy is AssetStrategy.archive_image:
            effect = VisualEffect.slow_push_in
        elif unit.source_strategy in {
            AssetStrategy.generated_graphic,
            AssetStrategy.document,
            AssetStrategy.text_card,
        }:
            if scene.effect is VisualEffect.none:
                effect = VisualEffect.slow_push_in
        scenes.append(
            scene.model_copy(
                update={
                    "metadata": meta,
                    "effect": effect,
                    "asset_strategy": unit.source_strategy,
                }
            )
        )
    return plan.model_copy(update={"scenes": scenes})


def _stamp_unit_progress(plan: ScenePlan, asset_plan: AssetPlan) -> ScenePlan:
    by_id = {scene.id: scene for scene in plan.scenes}
    updated = {scene.id: scene for scene in plan.scenes}
    for unit in asset_plan.units:
        members = [by_id[scene_id] for scene_id in unit.scene_ids]
        total = sum(item.duration for item in members) or 1.0
        cursor = 0.0
        for item in members:
            start = cursor / total
            cursor += item.duration
            end = cursor / total
            meta = dict(item.metadata)
            meta["unit_progress_start"] = round(start, 6)
            meta["unit_progress_end"] = round(end, 6)
            meta["unit_duration"] = round(total, 4)
            updated[item.id] = item.model_copy(update={"metadata": meta})
    return plan.model_copy(update={"scenes": [updated[scene.id] for scene in plan.scenes]})


def _generate_missing_local_graphics(
    paths: ProjectPaths, project: Project, plan: ScenePlan, asset_plan: AssetPlan
) -> AssetPlan:
    scenes = {scene.id: scene for scene in plan.scenes}
    units: list[AssetUnit] = []
    for unit in asset_plan.units:
        if unit.source_strategy not in {
            AssetStrategy.generated_graphic,
            AssetStrategy.document,
            AssetStrategy.map,
            AssetStrategy.text_card,
        }:
            units.append(unit)
            continue
        scene = scenes[unit.scene_ids[0]]
        manifest = execute_generate_graphic(paths, scene=scene, seed=project.random_seed)
        units.append(
            unit.model_copy(
                update={
                    "status": "READY_LOCAL",
                    "provider": "local",
                    "source_path": manifest.output_path,
                    "estimated_cost": "0",
                }
            )
        )
    return asset_plan.model_copy(update={"units": units})


def retime_stock_units(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    seed: int,
) -> int:
    scenes = {scene.id: scene for scene in plan.scenes}
    retimed = 0
    for unit in asset_plan.units:
        if unit.source_strategy not in STOCK_STRATEGIES:
            continue
        members = [scenes[scene_id] for scene_id in unit.scene_ids]
        needed = sum(item.duration for item in members)
        source = None
        for item in members:
            candidate = paths.stock_source_mp4(item.id)
            if candidate.is_file():
                source = candidate
                break
        if source is None and unit.source_path:
            candidate = paths.root / unit.source_path
            if candidate.is_file():
                source = candidate
        if source is None:
            continue
        cursor = 0.0
        from docprod.render.ffmpeg import probe_media

        duration = probe_media(source).duration
        if duration < needed:
            continue
        start0 = pick_clip_start(
            source_duration=duration, needed=needed, seed=seed, scene_id=unit.asset_unit_id
        )
        cursor = 0.0
        for item in members:
            clip_start = start0 + cursor
            sha = normalize_stock_clip(
                source,
                paths.stock_clip_mp4(item.id),
                start=clip_start,
                duration=float(item.duration),
            )
            meta_path = paths.stock_source_meta(item.id)
            if meta_path.is_file():
                meta = load_model(meta_path, StockSourceManifest)
                save_model(
                    meta_path,
                    meta.model_copy(
                        update={
                            "clip_start": clip_start,
                            "clip_duration": float(item.duration),
                            "clip_sha256": sha,
                        }
                    ),
                )
            cursor += item.duration
            retimed += 1
    return retimed


def attach_runtime_fields(plan: ScenePlan, asset_plan: AssetPlan, timeline) -> None:
    by_scene = {}
    for unit in asset_plan.units:
        for scene_id in unit.scene_ids:
            by_scene[scene_id] = unit
    for timing in timeline.scenes:
        unit = by_scene[timing.scene_id]
        timing.asset_unit_id = unit.asset_unit_id
        timing.source_asset = unit.source_path
        timing.runtime_strategy = str(
            unit.extra.get("runtime_preview_strategy") or unit.source_strategy.value
        )


def future_video_preview(plan: ScenePlan, asset_plan: AssetPlan) -> list[dict]:
    scenes = {scene.id: scene for scene in plan.scenes}
    rows = []
    for unit in asset_plan.units:
        if unit.source_strategy is not AssetStrategy.ai_image_to_video:
            continue
        real = sum(scenes[scene_id].duration for scene_id in unit.scene_ids)
        rows.append(
            {
                "asset_unit_id": unit.asset_unit_id,
                "old_duration": unit.continuous_duration,
                "real_duration": round(real, 4),
                "motion_description": unit.visual_concept,
                "sora2_720p_preview_usd": round(real * 0.10, 4),
            }
        )
    return rows


def _image_cost_usd(usages: list[dict]) -> tuple[float | None, str]:
    if not usages:
        return None, "estimated: no usage returned"
    total = 0.0
    saw = False
    for usage in usages:
        text_in = usage.get("input_tokens") or usage.get("text_tokens")
        image_out = usage.get("output_tokens")
        image_in = 0
        details = usage.get("input_tokens_details")
        if isinstance(details, dict):
            image_in = details.get("image_tokens") or 0
            text_in = details.get("text_tokens") or text_in
        if text_in is None and image_out is None:
            continue
        saw = True
        total += float(text_in or 0) * 5 / 1_000_000
        total += float(image_in or 0) * 8 / 1_000_000
        total += float(image_out or 0) * 30 / 1_000_000
    if not saw:
        return None, "price unresolved: usage present but token fields missing"
    return round(total, 6), "measured from returned token usage"


def _tts_cost_usd(usage: dict | None) -> tuple[float | None, str]:
    if not usage:
        return None, "price unresolved: no TTS usage returned"
    text_in = usage.get("input_tokens") or usage.get("prompt_tokens")
    audio_out = usage.get("output_tokens") or usage.get("completion_tokens")
    if text_in is None and audio_out is None:
        return None, "price unresolved: TTS usage missing token fields"
    total = float(text_in or 0) * 0.60 / 1_000_000 + float(audio_out or 0) * 12 / 1_000_000
    return round(total, 6), "measured from returned token usage"


def _costs_payload(
    *,
    image_jobs,
    narration,
    video_preview,
) -> dict:
    image_usages = []
    for job in image_jobs:
        meta = Path(job.meta_path)
        if meta.is_file():
            data = GeneratedImageManifest.model_validate_json(meta.read_text())
            if data.usage:
                image_usages.append(data.usage)
    image_usd, image_basis = _image_cost_usd(image_usages)
    tts_usage = None if narration is None else narration.meta.usage
    tts_usd, tts_basis = _tts_cost_usd(tts_usage if isinstance(tts_usage, dict) else None)
    whisper_minutes = 0.0
    if narration is not None:
        whisper_minutes = narration.meta.duration / 60.0
    whisper_cost = round(whisper_minutes * 0.006, 6) if narration else 0.0
    known = [item for item in (image_usd, tts_usd, whisper_cost) if item is not None]
    return {
        "image_calls": max(
            sum(0 if job.cached else 1 for job in image_jobs),
            len(image_usages),
        ),
        "image_cached": sum(1 for job in image_jobs if job.cached),
        "image_usages": image_usages,
        "image_cost_usd": image_usd,
        "image_cost_basis": image_basis,
        "tts_usage": tts_usage,
        "tts_cost_usd": tts_usd,
        "tts_cost_basis": tts_basis,
        "whisper_minutes": round(whisper_minutes, 4),
        "whisper_cost_usd": whisper_cost,
        "whisper_cost_basis": "measured $0.006/minute",
        "known_total_usd": round(sum(known), 6) if known else None,
        "future_ai_video_sora2_720p": video_preview,
        "notes": [
            "GPT Image 2.5 Flare: $5/1M text, $8/1M image in, $30/1M image out.",
            "TTS: $0.60/1M text in, $12/1M audio out when usage present.",
            "Sora 2 720p $0.10/sec is a reference preview only; provider not selected.",
        ],
    }


def prepare_review_episode(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
) -> tuple[ScenePlan, AssetPlan, ReviewDryRun]:
    plan, asset_plan = convert_info_graphic_units(plan, asset_plan)
    plan = _stamp_units_on_scenes(plan, asset_plan)
    asset_plan = _generate_missing_local_graphics(paths, project, plan, asset_plan)
    plan = _stamp_units_on_scenes(plan, asset_plan)
    save_model(paths.scene_plan_json, plan)
    save_model(paths.asset_plan_json(), asset_plan)
    script = build_canonical_script(plan)
    tts = inspect_tts_input(script.text)
    config = ImageGenerationConfig.from_settings()
    jobs = plan_review_image_jobs(
        paths, plan=plan, asset_plan=asset_plan, config=config, seed=project.random_seed
    )
    paid = sum(1 for job in jobs if not job.cached)
    counts: dict[str, int] = {}
    for scene in plan.scenes:
        counts[scene.asset_strategy.value] = counts.get(scene.asset_strategy.value, 0) + 1
    dry = ReviewDryRun(
        scene_count=len(plan.scenes),
        asset_unit_count=len(asset_plan.units),
        strategy_counts=dict(sorted(counts.items())),
        paid_image_requests=paid,
        tts_requests=1 if tts.within_limit else 0,
        whisper_requests=1 if tts.within_limit else 0,
        video_model_requests=0,
        image_model=config.model,
        image_quality=config.quality,
        tts_model="gpt-4o-mini-tts",
        tts_voice="cedar",
        tts_chars=tts.character_count,
        tts_tokens=tts.estimated_tokens,
        tts_within_limit=tts.within_limit,
        tts_reason=tts.reason,
        output_paths=[
            str(paths.preview_narrated_mp4()),
            str(paths.runtime_timeline_json()),
            str(paths.paid_visuals_contact_sheet()),
            str(paths.production_costs_json()),
        ],
    )
    return plan, asset_plan, dry


def execute_review_episode(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    confirm_paid: bool,
    image_provider=None,
    tts=None,
    whisper=None,
    skip_render: bool = False,
) -> tuple[ReviewDryRun, AssetPlan]:
    plan, asset_plan, dry = prepare_review_episode(
        paths, project=project, plan=plan, asset_plan=asset_plan
    )
    if dry.paid_image_requests > 7:
        from docprod.exceptions import MaxPaidRequestsExceededError

        raise MaxPaidRequestsExceededError(
            f"Paid image requests {dry.paid_image_requests} exceed corrected max 7."
        )
    budget = ModelRequestBudget(dry.paid_image_requests)
    jobs, asset_plan = generate_review_images(
        paths,
        project=project,
        plan=plan,
        asset_plan=asset_plan,
        confirm_paid=confirm_paid,
        provider=image_provider,
        budget=budget,
    )
    write_paid_visuals_sheet(paths, jobs)
    plan = _stamp_units_on_scenes(plan, asset_plan)
    save_model(paths.asset_plan_json(), asset_plan)
    save_model(paths.scene_plan_json, plan)
    require_zero_placeholders(paths, plan)
    if not dry.tts_within_limit:
        save_json(
            paths.production_costs_json(),
            _costs_payload(
                image_jobs=jobs,
                narration=None,
                video_preview=future_video_preview(plan, asset_plan),
            ),
        )
        raise TtsInputLimitError(dry.tts_reason)
    narration = generate_narration(
        paths,
        project=project,
        plan=plan,
        confirm_paid=confirm_paid,
        tts=tts,
        whisper=whisper,
    )
    timeline = narration.timeline
    attach_runtime_fields(plan, asset_plan, timeline)
    save_model(paths.runtime_timeline_json(), timeline)
    runtime_plan = apply_runtime_timeline(plan, timeline)
    runtime_plan = _stamp_unit_progress(runtime_plan, asset_plan)
    retime_stock_units(
        paths, plan=runtime_plan, asset_plan=asset_plan, seed=project.random_seed
    )
    video_preview = future_video_preview(runtime_plan, asset_plan)
    save_json(
        paths.production_costs_json(),
        _costs_payload(image_jobs=jobs, narration=narration, video_preview=video_preview),
    )
    if skip_render:
        return dry, asset_plan
    render_preview(
        paths,
        project=project,
        plan=runtime_plan,
        profile=PreviewRenderProfile(segment_workers=4),
        workers=4,
        use_cache=True,
        output_mp4=paths.preview_narrated_mp4(),
        manifest_path=paths.preview_narrated_manifest(),
        captions_srt=paths.captions_narrated_srt(),
        captions_ass=paths.captions_narrated_ass(),
        narration_wav=paths.narration_master_wav(),
        allow_placeholders=False,
        alignment=narration.alignment,
    )
    return dry, asset_plan
