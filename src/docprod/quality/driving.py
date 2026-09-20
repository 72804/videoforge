from __future__ import annotations

from docprod.models.scene import Scene
from docprod.quality.catalog import get_model
from docprod.quality.specs import DrivingPerformancePlan

_BEAT_MOTIONS: dict[str, list[str]] = {
    "b07": [
        "T=0.00–1.50 (reference clock): settle; cola/hand action on “Bir kola aldı”",
        "T=1.50–2.10: mouth “Kemal’e yaz.” at Cedar pace (do not imitate the voice)",
        "T=2.10–2.92: hold while Cedar pauses",
        "T=2.92–3.56: stay still through “Bakkal baktı”",
        "T=4.28–5.22: small confident wink / smirk (Cedar “göz kırptı”)",
        "hold through ~8s; do not voice-match Cedar",
    ],
    "b15": [
        "hold ground inside the apartment",
        "shift weight as if expecting a punch",
        "Müge stands still",
        "Kemal only nods — no swing",
        "hold the standoff",
    ],
    "b17": [
        "set cola on the bakkal counter",
        "speak “Kemal’e yaz” with the old confidence",
        "watch the grocer close the ledger",
        "face falls as the line lands",
        "hold the payoff beat",
    ],
    "b18": [
        "reach into a jacket pocket",
        "small, unfinished gesture",
        "no celebrity impersonation",
        "hold a quiet last frame",
    ],
}


def model_requires_manual_driving(model_id: str) -> bool:
    spec = get_model(model_id)
    return bool(spec and spec.manual_input_required)


def needs_driving_performance(
    scene: Scene,
    *,
    model_id: str = "",
    driving_video: str = "",
    allow_manual_inputs: bool = False,
) -> bool:
    """True only when a transfer model is selected AND a driving clip is usable.

    Human recording is never implied. Missing driving + allow_manual_inputs=false
    means the router must pick an automated fallback instead.
    """
    _ = scene
    if not model_requires_manual_driving(model_id):
        return False
    if driving_video:
        return True
    return allow_manual_inputs


def driving_plan_for(scene: Scene) -> DrivingPerformancePlan:
    beat = str((scene.metadata or {}).get("beat_id") or "")
    chars = [str(c) for c in (scene.metadata or {}).get("characters") or []]
    motions = list(_BEAT_MOTIONS.get(beat) or _motions_from_intent(scene))
    camera = "locked medium shot"
    if beat == "b07":
        camera = "locked medium, chest/waist-up, eye level or slightly below"
    elif "wide" in scene.visual_intent.casefold() or "door" in scene.visual_intent.casefold():
        camera = "locked wide, no handheld whip-pans"
    duration_note = f"~{scene.duration:.1f} sec scene window (record 3–30s; Act-Two requires ≥3s)"
    if beat == "b07":
        duration_note = (
            "record 7–9s driving take (Act-Two bills driving length, 3–30s); "
            f"episode scene window is ~{scene.duration:.1f}s after trim"
        )
    lines = [
        f"Scene: {scene.visual_intent.strip()}",
        "",
        f"Duration: {duration_note}",
        "",
        "Performance:",
        *[f"- {item}" for item in motions],
        "",
        f"Camera: {camera}",
        "",
        "Audio: play b07_recording_assist.wav in one earbud; match Cedar timing only.",
        "",
        f"Narration/dialogue in scene: {scene.narration.strip()}",
    ]
    return DrivingPerformancePlan(
        scene_id=scene.id,
        duration=scene.duration,
        dialogue_audio_target=scene.narration.strip(),
        required_motions=motions,
        camera_behavior=camera,
        number_of_performers=max(1, len(chars)),
        recording_instructions="\n".join(lines),
        reference_character_bindings=chars,
        needs_driving_performance=False,
    )


def _motions_from_intent(scene: Scene) -> list[str]:
    text = f"{scene.visual_intent} {scene.narration}".casefold()
    out = ["enter or settle in frame", "perform the visible action once", "hold final expression"]
    if "kola" in text or "cola" in text:
        out.insert(1, "place the bottle on the counter")
    if "kapı" in text:
        out.insert(1, "open the door toward camera")
    if "cep" in text or "pocket" in text:
        out.insert(1, "reach into a pocket")
    return out
