from __future__ import annotations

from docprod.audio.models import RuntimeTimeline
from docprod.models.scene import ScenePlan
from docprod.quality.enums import QualityProfile

VEO_LITE = "veo-3.1-lite-generate-preview"
GEN45 = "runway-gen-4.5"

# Locked Birko custom-character V2: Veo 3.1 Lite only. No Runway / Act-Two.
BIRKO_V2_BALANCED_ROUTES: dict[str, str] = {
    "b06": VEO_LITE,
    "b07": VEO_LITE,
    "b09": VEO_LITE,
    "b13": VEO_LITE,
    "b14": VEO_LITE,
    "b15": VEO_LITE,
    "b17": VEO_LITE,
    "b18": VEO_LITE,
}

IDENTITY_LOCK = (
    "Animate the approved source still; do not redesign the shot. "
    "Preserve every face, age, hairstyle, body appearance, clothing from the source frame, "
    "number of people, location, composition, scene action, and photographic style. "
    "Restrained natural motion only. "
    "Avoid face morphing, identity drift, character substitution, adding people, "
    "removing people, wardrobe transformation, sudden camera teleportation, "
    "excessive gestures, surreal motion, and unnecessary speaking."
)

B07_I2V_PROMPT = (
    "Animate the approved bakkal still. Keep Birko's face, age, hair, wardrobe, "
    "and the grocer. Subtle conversational body motion; dialogue is implied only, "
    "no lip-sync close-up, no prominent mouth articulation. Natural afternoon light, "
    "35mm grain. No redesign, morphing, extra people, or camera teleport."
)

V2_HARD_CAP_USD = 3.20
V2_EXPECTED_USD = 3.20
V2_VEO_BILLABLE_SECONDS = 64.0
V2_GEN45_BILLABLE_SECONDS = 0.0
V2_VEO_USD = 3.20
V2_GEN45_USD = 0.0
V2_PRIORITY = ("b15", "b17", "b07", "b18", "b13", "b09", "b14", "b06")
V2_BILLABLE_SECONDS: dict[str, int] = {
    "b06": 8,
    "b07": 8,
    "b09": 8,
    "b13": 8,
    "b14": 8,
    "b15": 8,
    "b17": 8,
    "b18": 8,
}

B09_I2V_PROMPT = (
    "Animate the kitchen still. Keep Kemal's face and wardrobe. Small weight shift "
    "and restrained suspicion as he notices perfume. No melodrama, morphing, or extra people."
)
B13_I2V_PROMPT = (
    "Animate the bedroom-mirror still. Keep Müge's face and wardrobe. Subtle earring "
    "or hand adjustment and a small decision in her expression. No glamour-ad lighting."
)
B14_I2V_PROMPT = (
    "Animate the apartment-door still. Keep the same people and interior. Quiet tension, "
    "controlled movement. No horror, jump scare, extra people, or redesign."
)
B06_I2V_PROMPT = (
    "Animate the bakkal-chair still. Keep Birko's face and wardrobe. Small natural body "
    "and environment motion, relaxed entitlement. No cartoon walk or redesign."
)
B18_I2V_PROMPT = (
    "Animate the bakkal payoff still. Keep Birko's face and wardrobe. He reaches into "
    "his jacket pocket with restrained physical comedy. No cartoon acting or redesign."
)
B15_I2V_PROMPT = (
    f"{IDENTITY_LOCK} "
    "Photorealistic cinematic image-to-video of a modest Turkish apartment. "
    "THREE DISTINCT PEOPLE must remain clearly separated: Birko, Müge, and Kemal "
    "exactly as in the source still. Preserve all three identities over ambitious "
    "movement. Restrained blocking only. Do not merge faces or bodies. "
    "Do not add or remove characters. No fight, no shouting, no action-movie camera."
)
B17_I2V_PROMPT = (
    f"{IDENTITY_LOCK} "
    "Photorealistic cinematic image-to-video of a neighborhood bakkal. The shopkeeper "
    "closes a paper ledger with a clear hand action. Birko is present and reacts "
    "with small natural motion, same faces as the source still."
)
V2_PROMPTS: dict[str, str] = {
    "b06": B06_I2V_PROMPT,
    "b07": B07_I2V_PROMPT,
    "b09": B09_I2V_PROMPT,
    "b13": B13_I2V_PROMPT,
    "b14": B14_I2V_PROMPT,
    "b15": B15_I2V_PROMPT,
    "b17": B17_I2V_PROMPT,
    "b18": B18_I2V_PROMPT,
}
V2_NEGATIVE = (
    "identity drift, extra people, morphing hands, cartoon acting, readable text, "
    "collage, horror, glamour commercial, fight scene"
)
B07_I2V_NEGATIVE = (
    "front-facing lip close-up, large articulated mouth, talking animation, "
    "unsynchronized speech, cartoon acting, morphing fingers, extra people, "
    "readable text, identity change"
)


def locked_video_models(plan: ScenePlan, profile: QualityProfile) -> dict[str, str]:
    beats = {str((s.metadata or {}).get("beat_id") or "") for s in plan.scenes}
    if profile is QualityProfile.BALANCED and "b07" in beats and "b15" in beats:
        return dict(BIRKO_V2_BALANCED_ROUTES)
    return {}


def apply_runtime_durations(plan: ScenePlan, timeline: RuntimeTimeline) -> ScenePlan:
    by_id = {item.scene_id: item for item in timeline.scenes}
    scenes = []
    for scene in plan.scenes:
        item = by_id.get(scene.id)
        if item is None:
            scenes.append(scene)
            continue
        scenes.append(
            scene.model_copy(
                update={
                    "start": item.start,
                    "end": item.end,
                    "duration": item.duration,
                }
            )
        )
    return plan.model_copy(update={"scenes": scenes})
