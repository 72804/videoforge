from __future__ import annotations

from docprod.quality.enums import EnsembleRole, QualityProfile
from docprod.quality.policy_select import script_model_for

PROMPT_VERSION_TREATMENT = "friend_group_treatment_v1"
PROMPT_VERSION_CRITIC = "friend_group_opus_critic_v1"
PROMPT_VERSION_FINAL = "friend_group_final_script_v1"

CRITIC_SYSTEM = """
You are an independent script doctor for friend-group short videos.
Return STRUCTURED critique only. Do not rewrite the whole episode.
Score each field 0-10 as a production heuristic, not scientific truth:
hook_strength, character_specificity, dialogue_naturalness, escalation,
joke_repetition, pacing, visual_opportunity, emotional_clarity, payoff,
shareability, persona_consistency, duration_feasibility_45_60s,
callback_quality, production_feasibility, continuity, inside_joke_usage.
Also list: keep, change, reject_if_blindly_applied, memeable_moments,
feasibility_risks. Prefer authenticity over generic AI-story polish.
Do not pick a numeric winner blindly. Identify strengths to keep.
""".strip()


def uses_premium_script_ensemble(profile: QualityProfile, *, flagship: bool = False) -> bool:
    return flagship or profile in {QualityProfile.PREMIUM, QualityProfile.MAX_QUALITY}


def script_ensemble_plan(
    profile: QualityProfile,
    *,
    flagship: bool = False,
    override: str = "auto",
) -> dict[str, object]:
    """PRIMARY → optional CRITIC → FINALIZER. Economy/Balanced stay single-model."""
    primary = script_model_for(profile, override=override, flagship=flagship)
    if not uses_premium_script_ensemble(profile, flagship=flagship):
        return {
            "ensemble": False,
            EnsembleRole.PRIMARY_MODEL.value: primary,
            EnsembleRole.CRITIC_MODEL.value: "",
            EnsembleRole.FINALIZER_MODEL.value: primary,
            "prompt_versions": {
                "treatment": PROMPT_VERSION_TREATMENT,
                "final": PROMPT_VERSION_FINAL,
            },
        }
    return {
        "ensemble": True,
        EnsembleRole.PRIMARY_MODEL.value: "gpt-6-astra",
        EnsembleRole.CRITIC_MODEL.value: "claude-opus-5-5",
        EnsembleRole.FINALIZER_MODEL.value: "gpt-6-astra",
        "prompt_versions": {
            "treatment": PROMPT_VERSION_TREATMENT,
            "critic": PROMPT_VERSION_CRITIC,
            "final": PROMPT_VERSION_FINAL,
        },
        "critic_system": CRITIC_SYSTEM,
        "finalizer_rule": "Incorporate useful critique; do not blindly obey every suggestion.",
        "treatment_count": 3,
    }
