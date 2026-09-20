from __future__ import annotations

from docprod.quality.enums import SceneProductionClass
from docprod.quality.specs import SceneValueScore

# Relative quality gain vs a competent still. Inspectable heuristics, not ML.
GAIN: dict[SceneProductionClass, dict[str, float]] = {
    SceneProductionClass.STATIC_CINEMATIC: {
        "still": 0.55,
        "local_motion": 0.72,
        "cheap_video": 0.78,
        "premium_video": 0.82,
        "performance": 0.50,
        "dialogue": 0.45,
    },
    SceneProductionClass.ESTABLISHING_SHOT: {
        "still": 0.60,
        "local_motion": 0.74,
        "cheap_video": 0.80,
        "premium_video": 0.84,
        "performance": 0.40,
        "dialogue": 0.30,
    },
    SceneProductionClass.SIMPLE_MOTION: {
        "still": 0.28,
        "local_motion": 0.55,
        "cheap_video": 0.78,
        "premium_video": 0.84,
        "performance": 0.50,
        "dialogue": 0.35,
    },
    SceneProductionClass.REACTION_SHOT: {
        "still": 0.32,
        "local_motion": 0.50,
        "cheap_video": 0.80,
        "premium_video": 0.88,
        "performance": 0.55,
        "dialogue": 0.40,
    },
    SceneProductionClass.DIALOGUE_SHOT: {
        "still": 0.18,
        "local_motion": 0.28,
        "cheap_video": 0.48,
        "premium_video": 0.62,
        "performance": 0.70,
        "dialogue": 0.92,
    },
    SceneProductionClass.HERO_CINEMATIC: {
        "still": 0.35,
        "local_motion": 0.52,
        "cheap_video": 0.74,
        "premium_video": 0.95,
        "performance": 0.70,
        "dialogue": 0.60,
    },
    SceneProductionClass.PERFORMANCE_SHOT: {
        "still": 0.15,
        "local_motion": 0.22,
        "cheap_video": 0.40,
        "premium_video": 0.55,
        "performance": 0.96,
        "dialogue": 0.70,
    },
    SceneProductionClass.MUSIC_SYNCED_PERFORMANCE: {
        "still": 0.10,
        "local_motion": 0.16,
        "cheap_video": 0.28,
        "premium_video": 0.35,
        "performance": 0.97,
        "dialogue": 0.40,
    },
    SceneProductionClass.TITLE_CARD: {
        "still": 1.0,
        "local_motion": 0.2,
        "cheap_video": 0.05,
        "premium_video": 0.05,
        "performance": 0.0,
        "dialogue": 0.0,
    },
    SceneProductionClass.ARCHIVAL_SHOT: {
        "still": 0.90,
        "local_motion": 0.70,
        "cheap_video": 0.40,
        "premium_video": 0.40,
        "performance": 0.10,
        "dialogue": 0.10,
    },
    SceneProductionClass.TRANSITION_SHOT: {
        "still": 0.40,
        "local_motion": 0.65,
        "cheap_video": 0.55,
        "premium_video": 0.50,
        "performance": 0.10,
        "dialogue": 0.05,
    },
}


def quality_gain(production_class: SceneProductionClass, technique: str) -> float:
    table = GAIN.get(production_class) or GAIN[SceneProductionClass.STATIC_CINEMATIC]
    return table.get(technique, 0.3)


def utility(
    scores: SceneValueScore,
    *,
    production_class: SceneProductionClass,
    technique: str,
    estimated_cost: float | None,
) -> float:
    gain = quality_gain(production_class, technique)
    cost = estimated_cost if estimated_cost and estimated_cost > 0 else 0.08
    return (gain * scores.story_importance) / cost
