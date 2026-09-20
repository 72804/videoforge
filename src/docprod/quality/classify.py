from __future__ import annotations

import re

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene
from docprod.quality.enums import SceneProductionClass, SfxClass, StoryFunction
from docprod.quality.specs import SceneValueScore

# Drama beat hints from the locked Birko script. Heuristics stay inspectable.
DRAMA_BEAT_CLASS: dict[str, SceneProductionClass] = {
    "b01": SceneProductionClass.ESTABLISHING_SHOT,
    "b02": SceneProductionClass.STATIC_CINEMATIC,
    "b03": SceneProductionClass.STATIC_CINEMATIC,
    "b03b": SceneProductionClass.STATIC_CINEMATIC,
    "b04": SceneProductionClass.STATIC_CINEMATIC,
    "b05": SceneProductionClass.STATIC_CINEMATIC,
    "b06": SceneProductionClass.SIMPLE_MOTION,
    "b07": SceneProductionClass.DIALOGUE_SHOT,
    "b08": SceneProductionClass.STATIC_CINEMATIC,
    "b09": SceneProductionClass.REACTION_SHOT,
    "b10": SceneProductionClass.STATIC_CINEMATIC,
    "b11": SceneProductionClass.STATIC_CINEMATIC,
    "b12": SceneProductionClass.STATIC_CINEMATIC,
    "b13": SceneProductionClass.REACTION_SHOT,
    "b13b": SceneProductionClass.STATIC_CINEMATIC,
    "b14": SceneProductionClass.SIMPLE_MOTION,
    "b15": SceneProductionClass.HERO_CINEMATIC,
    "b15b": SceneProductionClass.STATIC_CINEMATIC,
    "b16": SceneProductionClass.STATIC_CINEMATIC,
    "b17": SceneProductionClass.HERO_CINEMATIC,
    "b18": SceneProductionClass.PERFORMANCE_SHOT,
}

DRAMA_BEAT_FUNCTION: dict[str, StoryFunction] = {
    "b01": StoryFunction.HOOK,
    "b02": StoryFunction.SETUP,
    "b03": StoryFunction.SETUP,
    "b03b": StoryFunction.SETUP,
    "b04": StoryFunction.COMEDIC_BEAT,
    "b05": StoryFunction.SETUP,
    "b06": StoryFunction.ESCALATION,
    "b07": StoryFunction.ESCALATION,
    "b08": StoryFunction.ESCALATION,
    "b09": StoryFunction.REVEAL,
    "b10": StoryFunction.COMEDIC_BEAT,
    "b11": StoryFunction.REVERSAL,
    "b12": StoryFunction.ESCALATION,
    "b13": StoryFunction.REVEAL,
    "b13b": StoryFunction.ESCALATION,
    "b14": StoryFunction.CONFRONTATION,
    "b15": StoryFunction.CONFRONTATION,
    "b15b": StoryFunction.REVERSAL,
    "b16": StoryFunction.CALLBACK,
    "b17": StoryFunction.PAYOFF,
    "b18": StoryFunction.RESOLUTION,
}

_ONSCREEN_DIALOGUE = re.compile(
    r"(kemal[’']e yaz|o öder|kararın buysa|ödemiyor|yarın da böyle)",
    re.IGNORECASE,
)


def classify_scene(scene: Scene) -> SceneProductionClass:
    meta = scene.metadata or {}
    hint = str(meta.get("production_class_hint") or meta.get("production_class") or "")
    if hint:
        try:
            return SceneProductionClass(hint)
        except ValueError:
            pass
    if meta.get("cinematic_title_card") or scene.asset_strategy is AssetStrategy.text_card:
        return SceneProductionClass.TITLE_CARD
    if scene.asset_strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}:
        return SceneProductionClass.ARCHIVAL_SHOT
    if meta.get("music_sync_required"):
        return SceneProductionClass.MUSIC_SYNCED_PERFORMANCE
    beat = str(meta.get("beat_id") or "")
    if beat in DRAMA_BEAT_CLASS:
        return DRAMA_BEAT_CLASS[beat]
    text = f"{scene.narration} {scene.visual_intent}".casefold()
    if _ONSCREEN_DIALOGUE.search(text) and "“" in scene.narration:
        return SceneProductionClass.DIALOGUE_SHOT
    if any(token in text for token in ("kapı", "kapıyı", "gir", "merdiven", "yürü")):
        return SceneProductionClass.SIMPLE_MOTION
    if any(token in text for token in ("yüz", "bakış", "tepki", "parfüm", "küpe")):
        return SceneProductionClass.REACTION_SHOT
    if any(token in text for token in ("depo", "dışarı", "sokak", "cadde", "warehouse")):
        return SceneProductionClass.ESTABLISHING_SHOT
    return SceneProductionClass.STATIC_CINEMATIC


def story_function_for(scene: Scene) -> StoryFunction:
    if (scene.metadata or {}).get("cinematic_title_card"):
        return StoryFunction.TITLE
    beat = str((scene.metadata or {}).get("beat_id") or "")
    if beat in DRAMA_BEAT_FUNCTION:
        return DRAMA_BEAT_FUNCTION[beat]
    purpose = str((scene.metadata or {}).get("purpose") or scene.visual_intent).casefold()
    if "hook" in purpose or "cold" in purpose:
        return StoryFunction.HOOK
    if "payoff" in purpose:
        return StoryFunction.PAYOFF
    return StoryFunction.SETUP


BEAT_STORY_OVERRIDE: dict[str, float] = {
    "b06": 0.88,
    "b07": 0.91,
    "b09": 0.86,
    "b13": 0.84,
    "b14": 0.88,
    "b15": 0.93,
    "b17": 0.96,
    "b18": 0.87,
}


def score_scene(scene: Scene, production_class: SceneProductionClass) -> SceneValueScore:
    fn = story_function_for(scene)
    story = {
        StoryFunction.HOOK: 0.92,
        StoryFunction.CONFRONTATION: 0.90,
        StoryFunction.PAYOFF: 0.95,
        StoryFunction.CALLBACK: 0.82,
        StoryFunction.REVEAL: 0.78,
        StoryFunction.REVERSAL: 0.80,
        StoryFunction.ESCALATION: 0.70,
        StoryFunction.RESOLUTION: 0.72,
        StoryFunction.COMEDIC_BEAT: 0.55,
        StoryFunction.SETUP: 0.45,
        StoryFunction.TITLE: 0.20,
        StoryFunction.BRIDGE: 0.25,
    }[fn]
    motion = {
        SceneProductionClass.STATIC_CINEMATIC: 0.18,
        SceneProductionClass.ESTABLISHING_SHOT: 0.28,
        SceneProductionClass.SIMPLE_MOTION: 0.72,
        SceneProductionClass.REACTION_SHOT: 0.64,
        SceneProductionClass.DIALOGUE_SHOT: 0.55,
        SceneProductionClass.HERO_CINEMATIC: 0.88,
        SceneProductionClass.PERFORMANCE_SHOT: 0.80,
        SceneProductionClass.MUSIC_SYNCED_PERFORMANCE: 0.95,
        SceneProductionClass.TITLE_CARD: 0.05,
        SceneProductionClass.ARCHIVAL_SHOT: 0.15,
        SceneProductionClass.TRANSITION_SHOT: 0.40,
    }[production_class]
    dialogue = 0.85 if production_class is SceneProductionClass.DIALOGUE_SHOT else 0.05
    if production_class is SceneProductionClass.DIALOGUE_SHOT:
        dialogue = 0.88
    beat = str((scene.metadata or {}).get("beat_id") or "")
    if beat in BEAT_STORY_OVERRIDE:
        story = BEAT_STORY_OVERRIDE[beat]
    chars = len((scene.metadata or {}).get("characters") or [])
    return SceneValueScore(
        story_importance=story,
        motion_need=motion,
        character_importance=min(1.0, 0.25 + 0.25 * chars),
        dialogue_importance=dialogue,
        performance_precision=0.85
        if production_class
        in {
            SceneProductionClass.PERFORMANCE_SHOT,
            SceneProductionClass.MUSIC_SYNCED_PERFORMANCE,
        }
        else 0.1,
        visual_novelty=0.55,
        emotional_intensity=story * 0.85,
        camera_complexity=motion * 0.6,
    ).clamp()


def sfx_class_for(scene: Scene) -> SfxClass | None:
    kind = str((scene.metadata or {}).get("planned_sfx") or "")
    if not kind:
        return None
    if kind in {"ledger_close", "door_reveal"}:
        return SfxClass.HERO_SFX
    if kind.endswith("_tone") or "ambience" in kind:
        return SfxClass.AMBIENCE
    if kind in {"cola_set", "pocket", "window_open"}:
        return SfxClass.FOLEY
    if "sting" in kind:
        return SfxClass.TRANSITION_STING
    return SfxClass.GENERIC_SFX
