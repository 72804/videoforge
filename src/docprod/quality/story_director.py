from __future__ import annotations

from docprod.quality.enums import EnsembleRole, QualityProfile
from docprod.quality.policy_select import script_model_for

PROMPT_VERSION_TREATMENT = "friend_group_treatment_v1"
PROMPT_VERSION_CRITIC = "friend_group_critic_v1"
PROMPT_VERSION_FINAL = "friend_group_final_script_v1"

CRITIC_SYSTEM = """
You are an independent script doctor for friend-group short videos.
This is a FRESH request. You have no hidden treatment-generation conversation.
Treatments below are explicit inputs only. Do not assume prior chat state.
Return STRUCTURED critique only. Do not rewrite the whole episode.
Evaluate:
- first 1-3 second hook
- character specificity and distinct dialogue voices
- consistency with each persona and relationship usage
- escalation, drama, dark/absurd comedy
- repetitive jokes and catchphrase overuse
- pacing, visual opportunity, shareability, payoff
- locked ending (Birko outside eating the last donut)
- feasibility in 45-60 seconds
Identify BEST ELEMENTS from each treatment, WEAKNESSES, WHAT TO REMOVE,
WHAT TO COMBINE, and WHAT THE FINALIZER SHOULD CHANGE.
Do not merely pick a numeric winner. The final version may synthesize
strengths from several treatments. Explain WHY something works or fails.
Score each field 0-10 as a production heuristic, not scientific truth:
hook_strength, character_specificity, dialogue_naturalness, escalation,
joke_repetition, pacing, visual_opportunity, emotional_clarity, payoff,
shareability, persona_consistency, duration_feasibility_45_60s,
callback_quality, production_feasibility, continuity, inside_joke_usage.
Also list: keep, change, reject_if_blindly_applied, memeable_moments,
feasibility_risks. Prefer authenticity over generic AI-story polish.
""".strip()

FINALIZER_SYSTEM = """
You produce the final shooting story as JSON matching FriendGroupStorySpec.
Use the locked premise and ending. Dialogue-first. Language from the brief.
Target 45-60 seconds. Synthesize useful critic notes; do not blindly obey.
Make an independent judgment. Do not invent a different ending.
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
        "critic_fresh_call": True,
        "treatment_count": 3,
    }
