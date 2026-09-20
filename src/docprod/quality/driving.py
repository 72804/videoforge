from __future__ import annotations

from docprod.models.scene import Scene
from docprod.quality.classify import classify_scene
from docprod.quality.enums import SceneProductionClass
from docprod.quality.specs import DrivingPerformancePlan

_BEAT_MOTIONS: dict[str, list[str]] = {
    "b07": [
        "enter frame or already at the counter",
        "place cola on the wood",
        "glance at the grocer",
        "small smirk",
        "speak “Kemal’e yaz.” then “O öder.”",
        "wink",
        "hold the final expression",
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


def needs_driving_performance(scene: Scene, *, model_id: str = "") -> bool:
    if "act-two" in model_id or "genjutsu" in model_id:
        return True
    klass = classify_scene(scene)
    if klass is SceneProductionClass.MUSIC_SYNCED_PERFORMANCE:
        return True
    return False


def driving_plan_for(scene: Scene) -> DrivingPerformancePlan:
    beat = str((scene.metadata or {}).get("beat_id") or "")
    chars = [str(c) for c in (scene.metadata or {}).get("characters") or []]
    motions = list(_BEAT_MOTIONS.get(beat) or _motions_from_intent(scene))
    camera = "locked medium shot"
    if "wide" in scene.visual_intent.casefold() or "door" in scene.visual_intent.casefold():
        camera = "locked wide, no handheld whip-pans"
    lines = [
        f"Scene: {scene.visual_intent.strip()}",
        "",
        f"Duration: ~{scene.duration:.1f} sec (record 3–30s; Act-Two requires ≥3s)",
        "",
        "Performance:",
        *[f"- {item}" for item in motions],
        "",
        f"Camera: {camera}",
        "",
        "Audio: use final dialogue timing; do not mime a celebrity.",
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
        needs_driving_performance=True,
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
