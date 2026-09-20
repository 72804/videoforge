from __future__ import annotations

from docprod.models.scene import ScenePlan
from docprod.quality.enums import QualityProfile
from docprod.quality.profiles import VIDEO_SECONDS, policy_for
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
    lines = [
        f"# Quality router plan — {project_id}",
        "",
        f"Profile: **{profile.value}**",
        f"Hard budget: ${policy.max_paid_usd:.2f} · target: ${policy.target_paid_usd:.2f}",
        f"Known new cost: ${cost.known_cost:.4f} · estimated: ${cost.estimated_cost:.4f}",
        f"Unresolved categories: {', '.join(cost.unresolved_categories) or 'none'}",
        "",
        "| scene | class | story | motion | dialogue | model | cost | why |",
        "|---|---|---|---|---|---|---|---|",
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
            f"{item.scores.story_importance:.2f} | {item.scores.motion_need:.2f} | "
            f"{item.scores.dialogue_importance:.2f} | {item.selected_model} | {cost_s} | "
            f"{item.reason} |"
        )
    lines.append("")
    lines.append(f"Video clip length assumed: {VIDEO_SECONDS:.0f}s (Veo Lite known option).")
    lines.append("No paid APIs were called.")
    return "\n".join(lines) + "\n"


def profile_summary(decisions: list[RouteDecision], cost: EpisodeCostPlan) -> dict:
    video = [
        d
        for d in decisions
        if d.selected_model
        not in {
            "local-camera",
            "local-title",
            "narration-over-image",
            "gpt-image-2.5-flare",
            "gpt-image-2.5-sunburst",
            "comfyui-local",
        }
        and d.production_class.value != "title_card"
        and "image" not in d.selected_model
    ]
    premium = [
        d
        for d in video
        if d.selected_model
        in {"veo-3.1-standard", "runway-gen-4.5", "runway-act-two", "higgsfield-genjutsu"}
    ]
    dialogue = [d for d in video if d.production_class.value == "dialogue_shot"]
    performance = [
        d
        for d in video
        if d.production_class.value in {"performance_shot", "music_synced_performance"}
    ]
    policy = policy_for(cost.profile)
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
        "video_seconds": round(VIDEO_SECONDS * len(video), 2),
        "premium_video_seconds": round(VIDEO_SECONDS * len(premium), 2),
        "performance_seconds": round(VIDEO_SECONDS * len(performance), 2),
        "dialogue_seconds": round(VIDEO_SECONDS * len(dialogue), 2),
        "tts_provider": policy.tts_model,
        "music_provider": policy.music_model,
        "premium_sfx_count": sum(
            1 for d in decisions if d.sfx_class and d.sfx_class.value == "hero_sfx"
        )
        if policy.premium_sfx
        else 0,
        "estimated_new_cost": cost.known_cost + cost.estimated_cost,
        "known_cost": cost.known_cost,
        "unresolved_cost": ",".join(cost.unresolved_categories) or "none",
        "video_scene_ids": [d.scene_id for d in video],
    }
