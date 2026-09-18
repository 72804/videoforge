from __future__ import annotations

import random

from docprod.models.enums import AssetStrategy, TransitionType, VisualEffect
from docprod.planning.effects import select_effect, select_transition
from docprod.planning.models import ContentCategory, VisualBeat
from docprod.planning.profile import ScenePlannerProfile


def test_repeated_effects_capped() -> None:
    profile = ScenePlannerProfile(max_consecutive_same_effect=2)
    previous = [VisualEffect.slow_push_in, VisualEffect.slow_push_in]
    rng = random.Random(0)
    effect, _reason = select_effect(
        AssetStrategy.ai_image,
        ContentCategory.generic,
        previous,
        rng,
        profile,
        visual_bridge=False,
    )
    assert effect is not VisualEffect.slow_push_in


def test_cut_is_default_transition() -> None:
    profile = ScenePlannerProfile()
    beat = VisualBeat(
        start=0,
        end=3,
        text="A man waited.",
        source_utterance_ids=["u"],
        segmentation_reason="keep",
    )
    transition, reason = select_transition(beat, ContentCategory.person, profile)
    assert transition is TransitionType.cut
    assert reason == "cut_default"
