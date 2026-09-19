from __future__ import annotations

from docprod.models.scene import ScenePlan
from docprod.production import AssetPlan, ProductionCostPreview
from docprod.writing.models import WORDS_PER_MINUTE, NarrationScript


def build_cost_preview(
    *,
    project_id: str,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    script: NarrationScript | None = None,
) -> ProductionCostPreview:
    units = asset_plan.units
    ai_still_units = [u for u in units if u.status == "NEEDS_AI_IMAGE"]
    ai_video_units = [u for u in units if u.status == "NEEDS_AI_VIDEO"]
    ai_still_scenes = sum(len(u.scene_ids) for u in ai_still_units)
    ai_video_scenes = sum(len(u.scene_ids) for u in ai_video_units)
    ai_video_seconds = sum(u.continuous_duration for u in ai_video_units)
    words = script.word_count if script else 0
    minutes = script.estimated_runtime_minutes if script else round(plan.total_duration / 60.0, 2)
    if not minutes and words:
        minutes = round(words / WORDS_PER_MINUTE, 2)
    notes = [
        "No paid visual/TTS/Whisper calls in this phase.",
        "AI image and AI-video dollar prices are unresolved until a pricing table is configured.",
        "Research Responses usage is recorded in prior stages; dollar cost unresolved.",
    ]
    return ProductionCostPreview(
        project_id=project_id,
        scene_count=len(plan.scenes),
        asset_unit_count=len(units),
        saved_generation_count=asset_plan.saved_generation_count,
        ai_still_scenes=ai_still_scenes,
        ai_still_units=len(ai_still_units),
        ai_video_scenes=ai_video_scenes,
        ai_video_units=len(ai_video_units),
        ai_video_seconds=round(ai_video_seconds, 3),
        narration_minutes=float(minutes or 0.0),
        pexels_assets=sum(1 for u in units if u.status == "READY_STOCK"),
        commons_assets=sum(1 for u in units if u.status == "READY_ARCHIVE"),
        local_assets=sum(1 for u in units if u.status == "READY_LOCAL"),
        known_image_cost="price unresolved",
        known_video_cost="price unresolved",
        known_tts_cost="price unresolved",
        known_whisper_cost="price unresolved",
        known_total="price unresolved",
        notes=notes,
    )


def strategy_counts(plan: ScenePlan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scene in plan.scenes:
        key = scene.asset_strategy.value
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
