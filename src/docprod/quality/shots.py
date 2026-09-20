from __future__ import annotations

from docprod.models.scene import Scene
from docprod.quality.classify import classify_scene
from docprod.quality.enums import SceneProductionClass
from docprod.quality.locked import B07_I2V_NEGATIVE, B07_I2V_PROMPT
from docprod.quality.specs import (
    AudioDrivenDialogueRequest,
    DialogueShotRequest,
    DrivingPerformanceAsset,
    PerformanceShotRequest,
)


def dialogue_request_for(
    scene: Scene, *, duration: float | None = None
) -> DialogueShotRequest | None:
    if classify_scene(scene) is not SceneProductionClass.DIALOGUE_SHOT:
        return None
    chars = list((scene.metadata or {}).get("characters") or [])
    return DialogueShotRequest(
        scene_id=scene.id,
        character_refs=[f"ref_{c}" if not str(c).startswith("ref_") else str(c) for c in chars],
        dialogue_text=scene.narration,
        duration=float(duration if duration is not None else scene.duration),
        emotion=scene.mood.value if hasattr(scene.mood, "value") else str(scene.mood),
        camera_instructions=scene.visual_intent,
    )


def audio_driven_request_for(
    scene: Scene, *, duration: float | None = None
) -> AudioDrivenDialogueRequest | None:
    if classify_scene(scene) is not SceneProductionClass.DIALOGUE_SHOT:
        return None
    chars = list((scene.metadata or {}).get("characters") or [])
    return AudioDrivenDialogueRequest(
        scene_id=scene.id,
        character_refs=[f"ref_{c}" if not str(c).startswith("ref_") else str(c) for c in chars],
        dialogue_text=scene.narration,
        emotion=scene.mood.value if hasattr(scene.mood, "value") else str(scene.mood),
        duration=float(duration if duration is not None else scene.duration),
        camera_framing=scene.visual_intent,
    )


def implied_dialogue_i2v_prompt(scene: Scene) -> str:
    beat = str((scene.metadata or {}).get("beat_id") or "")
    if beat == "b07":
        return B07_I2V_PROMPT
    return (
        f"{scene.visual_intent.strip()}. Restrained realistic motion, no exaggerated talking, "
        "identity preserved, cinematic naturalism."
    )


def implied_dialogue_negative(scene: Scene) -> str:
    beat = str((scene.metadata or {}).get("beat_id") or "")
    if beat == "b07":
        return B07_I2V_NEGATIVE
    return "exaggerated mouth movement, lip-sync close-up, identity drift"


def performance_request_for(
    scene: Scene, *, duration: float | None = None, driving: DrivingPerformanceAsset | None = None
) -> PerformanceShotRequest | None:
    klass = classify_scene(scene)
    if klass not in {
        SceneProductionClass.PERFORMANCE_SHOT,
        SceneProductionClass.MUSIC_SYNCED_PERFORMANCE,
    }:
        return None
    chars = list((scene.metadata or {}).get("characters") or [])
    return PerformanceShotRequest(
        scene_id=scene.id,
        driving_video=driving.path if driving else "",
        character_refs=[f"ref_{c}" if not str(c).startswith("ref_") else str(c) for c in chars],
        shot_duration=float(duration if duration is not None else scene.duration),
        camera_preservation=True,
        motion_preservation=True,
    )


def driving_placeholder(scene_id: str) -> DrivingPerformanceAsset:
    return DrivingPerformanceAsset(
        asset_id=f"drive_{scene_id}",
        source_kind="optional_manual",
        notes="Optional only. Automatic planning never waits for this asset.",
        celebrity_likeness=False,
    )
