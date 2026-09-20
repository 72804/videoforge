from __future__ import annotations

from docprod.models.scene import ScenePlan
from docprod.quality.enums import QualityProfile, UpgradeKind
from docprod.quality.profiles import policy_for
from docprod.quality.specs import EpisodeCostPlan, RouteDecision


def render_router_markdown(
    *,
    project_id: str,
    profile: QualityProfile,
    decisions: list[RouteDecision],
    cost: EpisodeCostPlan,
    plan: ScenePlan,
) -> str:
    policy = policy_for(profile)
    priced = "yes" if cost.fully_priced else "NO — do not treat known $ as a complete total"
    upper = (
        f"${cost.estimated_upper_bound_usd:.4f}"
        if cost.estimated_upper_bound_usd is not None
        else "n/a (unresolved items)"
    )
    lines = [
        f"# Quality router plan — {project_id}",
        "",
        f"Profile: **{profile.value}**",
        f"Hard budget: ${policy.max_paid_usd:.2f} · target: ${policy.target_paid_usd:.2f}",
        f"known_cost_usd: ${cost.known_cost:.4f}",
        f"estimated_lower_bound_usd: ${cost.estimated_lower_bound_usd:.4f}",
        f"estimated_upper_bound_usd: {upper}",
        f"fully_priced: {priced}",
        f"unresolved_cost_items: {', '.join(cost.unresolved_cost_items) or 'none'}",
        "",
        "| scene | class | upgrade | used s | billable s | waste s | model | cost | why |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_id = {scene.id: scene for scene in plan.scenes}
    for item in decisions:
        scene = by_id.get(item.scene_id)
        beat = ""
        if scene is not None:
            beat = str((scene.metadata or {}).get("beat_id") or "")
        cost_s = "UNRESOLVED" if item.estimated_cost is None else f"${item.estimated_cost:.3f}"
        if item.selected_model in {"local-camera", "local-title", "narration-over-image"}:
            cost_s = "$0"
        lines.append(
            f"| {item.scene_id} {beat} | {item.production_class.value} | "
            f"{item.upgrade_kind.value} | {item.used_seconds:.1f} | {item.billable_seconds:.1f} | "
            f"{item.wasted_seconds:.1f} | {item.selected_model} | {cost_s} | {item.reason} |"
        )
    video = [d for d in decisions if d.upgrade_kind is not UpgradeKind.STILL_LOCAL_MOTION]
    used = sum(d.used_seconds for d in video)
    billed = sum(d.billable_seconds for d in video)
    lines.append("")
    lines.append(
        f"Visible video seconds: {used:.1f} · billable: {billed:.1f} · "
        f"wasted generated: {max(0.0, billed - used):.1f}"
    )
    lines.append(
        "Cached stills, Cedar narration, Lyria, and generic SFX "
        "are reused unless upgraded."
    )
    lines.append("No paid APIs were called.")
    return "\n".join(lines) + "\n"


def profile_summary(decisions: list[RouteDecision], cost: EpisodeCostPlan) -> dict:
    video = [
        d
        for d in decisions
        if d.upgrade_kind is not UpgradeKind.STILL_LOCAL_MOTION
        and d.production_class.value != "title_card"
        and "image" not in d.selected_model
        and d.selected_model
        not in {"local-camera", "local-title", "narration-over-image", "comfyui-local"}
    ]
    premium = [
        d
        for d in video
        if d.selected_model
        in {"runway-gen-4.5", "runway-act-two", "higgsfield-genjutsu"}
    ]
    dialogue = [d for d in video if d.upgrade_kind.value == "dialogue_lipsync"]
    performance = [d for d in video if d.upgrade_kind.value == "performance_transfer"]
    policy = policy_for(cost.profile)
    used = sum(d.used_seconds for d in video)
    billed = sum(d.billable_seconds for d in video)
    display_cost = (
        cost.known_cost + cost.estimated_cost
        if cost.fully_priced
        else None
    )
    return {
        "total_scenes": len(decisions),
        "static_scenes": sum(
            1 for d in decisions if d.production_class.value == "static_cinematic"
        ),
        "simple_motion_scenes": sum(
            1 for d in decisions if d.production_class.value == "simple_motion"
        ),
        "reaction_scenes": sum(
            1 for d in decisions if d.production_class.value == "reaction_shot"
        ),
        "dialogue_scenes": sum(
            1 for d in decisions if d.production_class.value == "dialogue_shot"
        ),
        "hero_cinematic_scenes": sum(
            1 for d in decisions if d.production_class.value == "hero_cinematic"
        ),
        "performance_scenes": sum(
            1
            for d in decisions
            if d.production_class.value in {"performance_shot", "music_synced_performance"}
        ),
        "paid_image_count": 0,
        "video_seconds_used": round(used, 2),
        "video_seconds_billable": round(billed, 2),
        "wasted_seconds": round(max(0.0, billed - used), 2),
        "premium_video_seconds": round(sum(d.billable_seconds for d in premium), 2),
        "performance_seconds": round(sum(d.billable_seconds for d in performance), 2),
        "dialogue_seconds": round(sum(d.billable_seconds for d in dialogue), 2),
        "tts_provider": policy.tts_model,
        "music_provider": (
            "lyria-3.5 (cached reuse)"
            if cost.profile.value != "local_only"
            else policy.music_model
        ),
        "premium_sfx_count": sum(
            1 for d in decisions if d.sfx_class and d.sfx_class.value == "hero_sfx"
        )
        if policy.premium_sfx
        else 0,
        "known_cost_usd": cost.known_cost,
        "unresolved_cost_items": ",".join(cost.unresolved_cost_items) or "none",
        "estimated_lower_bound_usd": cost.estimated_lower_bound_usd,
        "estimated_upper_bound_usd": cost.estimated_upper_bound_usd,
        "fully_priced": cost.fully_priced,
        "estimated_new_cost": display_cost if display_cost is not None else "incomplete",
        "known_cost": cost.known_cost,
        "unresolved_cost": ",".join(cost.unresolved_categories) or "none",
        "video_scene_ids": [d.scene_id for d in video],
        "upgrade_kinds": {d.scene_id: d.upgrade_kind.value for d in video},
    }
