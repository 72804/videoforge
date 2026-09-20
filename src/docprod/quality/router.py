from __future__ import annotations

from docprod.quality.catalog import get_model
from docprod.quality.duration import billable_seconds
from docprod.quality.enums import (
    CostConfidence,
    QualityProfile,
    QualityTier,
    SceneProductionClass,
    UpgradeKind,
)
from docprod.quality.profiles import VIDEO_SECONDS, policy_for
from docprod.quality.specs import SceneValueScore


def estimate_model_cost(
    model_id: str,
    *,
    seconds: float | None = None,
    characters: float = 0.0,
) -> tuple[float | None, CostConfidence]:
    spec = get_model(model_id)
    if spec is None:
        return None, CostConfidence.UNRESOLVED
    price = spec.pricing
    if price.confidence is CostConfidence.UNRESOLVED or price.mode.value == "unknown":
        return None, CostConfidence.UNRESOLVED
    if price.value is None:
        return None, CostConfidence.UNRESOLVED
    if price.mode.value == "free":
        return 0.0, CostConfidence.KNOWN
    qty = VIDEO_SECONDS if seconds is None else seconds
    if price.mode.value == "per_second":
        billed = billable_seconds(model_id, qty)
        return round(price.value * billed, 6), price.confidence
    if price.mode.value == "per_request":
        return round(price.value, 6), price.confidence
    if price.mode.value == "per_minute":
        return round(price.value * (qty / 60.0), 6), price.confidence
    if price.mode.value == "per_character":
        return round(price.value * characters, 6), price.confidence
    return None, CostConfidence.UNRESOLVED


def automated_dialogue_chain(profile: QualityProfile) -> list[str]:
    """Never requires a human driving take. Act-Two is optional-only, not listed."""
    policy = policy_for(profile)
    if profile is QualityProfile.LOCAL_ONLY:
        return [
            policy.dialogue_model,
            "hunyuan-avatar-local",
            "ltx-local",
            "narration-over-image",
            "local-camera",
        ]
    if profile is QualityProfile.ECONOMY:
        return [policy.dialogue_model, "narration-over-image", "local-camera"]
    return [
        "audio-driven-lipsync",
        "veo-3.1-standard",
        policy.dialogue_model,
        "runway-gen-4.5",
        "veo-3.1-fast",
        "veo-3.1-lite-generate-preview",
        "narration-over-image",
        "local-camera",
    ]


def preferred_video_model(production_class: SceneProductionClass, profile: QualityProfile) -> str:
    policy = policy_for(profile)
    mapping = {
        SceneProductionClass.SIMPLE_MOTION: policy.simple_motion_model,
        SceneProductionClass.REACTION_SHOT: policy.reaction_model,
        SceneProductionClass.HERO_CINEMATIC: policy.hero_model,
        SceneProductionClass.DIALOGUE_SHOT: policy.dialogue_model,
        SceneProductionClass.PERFORMANCE_SHOT: policy.performance_model,
        SceneProductionClass.MUSIC_SYNCED_PERFORMANCE: policy.performance_model,
        SceneProductionClass.ESTABLISHING_SHOT: policy.simple_motion_model,
        SceneProductionClass.TRANSITION_SHOT: policy.simple_motion_model,
    }
    return mapping.get(production_class, "local-camera")


def fallback_chain(production_class: SceneProductionClass, profile: QualityProfile) -> list[str]:
    policy = policy_for(profile)
    if profile is QualityProfile.LOCAL_ONLY:
        if production_class is SceneProductionClass.DIALOGUE_SHOT:
            return automated_dialogue_chain(profile)
        if production_class in {
            SceneProductionClass.PERFORMANCE_SHOT,
            SceneProductionClass.MUSIC_SYNCED_PERFORMANCE,
        }:
            return [policy.performance_model, "ltx-local", "local-camera"]
        return [preferred_video_model(production_class, profile), "local-camera"]
    if production_class is SceneProductionClass.HERO_CINEMATIC:
        return [
            policy.hero_model,
            "runway-gen-4.5",
            "veo-3.1-lite-generate-preview",
            "local-camera",
        ]
    if production_class is SceneProductionClass.DIALOGUE_SHOT:
        return automated_dialogue_chain(profile)
    if production_class in {
        SceneProductionClass.PERFORMANCE_SHOT,
        SceneProductionClass.MUSIC_SYNCED_PERFORMANCE,
    }:
        return [
            policy.performance_model,
            "runway-gen-4.5",
            "veo-3.1-lite-generate-preview",
            "local-camera",
        ]
    return [
        preferred_video_model(production_class, profile),
        "veo-3.1-lite-generate-preview",
        "runway-gen-4.5",
        "local-camera",
    ]


def wants_video(
    production_class: SceneProductionClass,
    scores: SceneValueScore,
    profile: QualityProfile,
    *,
    music_sync: bool = False,
) -> bool:
    if production_class in {
        SceneProductionClass.TITLE_CARD,
        SceneProductionClass.ARCHIVAL_SHOT,
        SceneProductionClass.STATIC_CINEMATIC,
    }:
        return False
    if music_sync:
        return True
    policy = policy_for(profile)
    if production_class is SceneProductionClass.HERO_CINEMATIC:
        return scores.story_importance >= 0.75
    if production_class is SceneProductionClass.DIALOGUE_SHOT:
        return scores.dialogue_importance >= 0.7 and scores.story_importance >= 0.7
    if production_class is SceneProductionClass.PERFORMANCE_SHOT:
        return scores.performance_precision >= 0.7
    return scores.motion_need >= policy.motion_video_threshold


def technique_for_model(model_id: str) -> str:
    spec = get_model(model_id)
    if model_id in {"local-camera", "narration-over-image"}:
        return "local_motion" if model_id == "local-camera" else "still"
    if spec is None:
        return "cheap_video"
    caps = set(spec.capabilities)
    if "performance_transfer" in caps or "driving_video" in caps:
        return "performance"
    if "lip_sync" in caps or "dialogue" in caps:
        return "dialogue"
    if spec.quality_tier in {QualityTier.PREMIUM, QualityTier.MAX}:
        return "premium_video"
    if spec.local:
        return "cheap_video"
    return "cheap_video"


def still_route(scene_id: str, production_class: SceneProductionClass, profile: QualityProfile):
    from docprod.quality.enums import CostConfidence
    from docprod.quality.specs import RouteDecision

    policy = policy_for(profile)
    model = (
        "local-title"
        if production_class is SceneProductionClass.TITLE_CARD
        else policy.timeline_image_model
        if profile is not QualityProfile.LOCAL_ONLY
        else "comfyui-local"
    )
    if production_class is SceneProductionClass.TITLE_CARD:
        model = "local-title"
    provider = "local" if model.startswith("local") or model == "comfyui-local" else "openai"
    return RouteDecision(
        scene_id=scene_id,
        production_class=production_class,
        quality_profile=profile,
        selected_provider=provider,
        selected_model=model,
        fallback_chain=["local-camera"],
        estimated_cost=0.0,
        cost_confidence=CostConfidence.KNOWN,
        reason="Still/local motion is enough; motion does not change the beat enough.",
        quality_tier=policy.default_tier,
    )


def upgrade_kind_for(production_class: SceneProductionClass, model_id: str) -> UpgradeKind:
    if model_id in {"local-camera", "local-title", "narration-over-image"} or "image" in model_id:
        return UpgradeKind.STILL_LOCAL_MOTION
    spec = get_model(model_id)
    caps = set(spec.capabilities) if spec else set()
    if production_class is SceneProductionClass.DIALOGUE_SHOT:
        if "accepts_target_audio" in caps or (
            "lip_sync" in caps and "driving_video" not in caps
        ):
            return UpgradeKind.DIALOGUE_LIPSYNC
        return UpgradeKind.IMPLIED_DIALOGUE_I2V
    if production_class in {
        SceneProductionClass.PERFORMANCE_SHOT,
        SceneProductionClass.MUSIC_SYNCED_PERFORMANCE,
    }:
        if "performance_transfer" in caps or "driving_video" in caps:
            return UpgradeKind.PERFORMANCE_TRANSFER
        return UpgradeKind.SIMPLE_I2V
    if production_class is SceneProductionClass.HERO_CINEMATIC:
        return UpgradeKind.HERO_CINEMATIC
    if production_class is SceneProductionClass.REACTION_SHOT:
        return UpgradeKind.REACTION_I2V
    return UpgradeKind.SIMPLE_I2V
