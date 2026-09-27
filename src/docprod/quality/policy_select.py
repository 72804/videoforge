from __future__ import annotations

from docprod.quality.enums import QualityProfile, SceneProductionClass
from docprod.quality.profiles import policy_for
from docprod.quality.router import preferred_video_model, still_route

AUTO_TOKENS = frozenset({"", "auto"})

OPENAI_STOCK_VOICES = (
    "cedar",
    "marin",
    "coral",
    "verse",
    "sage",
    "ash",
    "ballad",
    "shimmer",
)


def resolve_override(explicit: str | None, routed: str) -> str:
    token = (explicit or "").strip()
    if token and token.lower() not in AUTO_TOKENS:
        return token
    return routed


def script_model_for(
    profile: QualityProfile,
    *,
    override: str = "auto",
    flagship: bool = False,
) -> str:
    routed = "gpt-6-astra" if flagship else policy_for(profile).script_model
    return resolve_override(override, routed)


def image_model_for(
    profile: QualityProfile,
    *,
    identity_critical: bool,
    key_still: bool = False,
    override: str = "auto",
) -> str:
    policy = policy_for(profile)
    if identity_critical or key_still:
        routed = policy.character_image_model
    else:
        routed = policy.timeline_image_model
    return resolve_override(override, routed)


def tts_model_for(
    profile: QualityProfile,
    *,
    dialogue: bool,
    override: str = "auto",
) -> str:
    policy = policy_for(profile)
    routed = policy.tts_model
    if (
        dialogue
        and profile in {QualityProfile.PREMIUM, QualityProfile.MAX_QUALITY}
        and override.lower() in AUTO_TOKENS
    ):
        routed = "eleven-v3"
    return resolve_override(override, routed)


def video_model_for(
    production_class: SceneProductionClass,
    profile: QualityProfile,
    *,
    override: str = "auto",
) -> str:
    routed = preferred_video_model(production_class, profile)
    return resolve_override(override, routed)


def still_model_for(
    production_class: SceneProductionClass,
    profile: QualityProfile,
    *,
    identity_critical: bool = False,
    override: str = "auto",
) -> str:
    if identity_critical:
        return image_model_for(profile, identity_critical=True, override=override)
    return resolve_override(override, still_route("plan", production_class, profile).selected_model)


def avoid_close_up_mouth(model_id: str) -> bool:
    spec = None
    from docprod.quality.catalog import get_model

    spec = get_model(model_id)
    if spec is None:
        return True
    return not spec.close_up_mouth_reliable
