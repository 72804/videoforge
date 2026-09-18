from __future__ import annotations

import random

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.planning.models import ContentCategory, VisualBeat
from docprod.planning.profile import ScenePlannerProfile

_VIDEO_EFFECTS = (
    VisualEffect.none,
    VisualEffect.documentary_handheld,
    VisualEffect.slow_push_in,
)
_STILL_EFFECTS = (
    VisualEffect.slow_push_in,
    VisualEffect.slow_pull_out,
    VisualEffect.pan_left,
    VisualEffect.pan_right,
    VisualEffect.parallax_2_5d,
)
_DOCUMENT_EFFECTS = (
    VisualEffect.photo_table,
    VisualEffect.newspaper_reveal,
    VisualEffect.slow_push_in,
)
_MAP_EFFECTS = (VisualEffect.map_route, VisualEffect.slow_push_in)
_POLICE_EFFECTS = (
    VisualEffect.surveillance_zoom,
    VisualEffect.cctv_treatment,
    VisualEffect.slow_push_in,
)
_GRAPHIC_EFFECTS = (VisualEffect.location_date_card, VisualEffect.slow_push_in)
_BRIDGE_EFFECTS = (VisualEffect.slow_push_in, VisualEffect.none)

_MOOD = {
    ContentCategory.crime: Mood.ominous,
    ContentCategory.danger: Mood.ominous,
    ContentCategory.police: Mood.tense,
    ContentCategory.money: Mood.urgent,
    ContentCategory.map_or_travel: Mood.mysterious,
    ContentCategory.time_establishing: Mood.mysterious,
    ContentCategory.action: Mood.chaotic,
    ContentCategory.news: Mood.tense,
    ContentCategory.person: Mood.neutral,
    ContentCategory.location_establishing: Mood.neutral,
}


def effect_pool(
    strategy: AssetStrategy,
    category: ContentCategory,
    *,
    visual_bridge: bool,
) -> tuple[VisualEffect, ...]:
    if visual_bridge:
        return _BRIDGE_EFFECTS
    if category in {ContentCategory.police, ContentCategory.crime, ContentCategory.danger}:
        return _POLICE_EFFECTS
    if strategy in {AssetStrategy.document}:
        return _DOCUMENT_EFFECTS
    if strategy is AssetStrategy.map:
        return _MAP_EFFECTS
    if strategy is AssetStrategy.generated_graphic:
        return _GRAPHIC_EFFECTS
    if strategy in {
        AssetStrategy.stock_video,
        AssetStrategy.archive_video,
        AssetStrategy.ai_image_to_video,
    }:
        return _VIDEO_EFFECTS
    return _STILL_EFFECTS


def select_effect(
    strategy: AssetStrategy,
    category: ContentCategory,
    previous: list[VisualEffect],
    rng: random.Random,
    profile: ScenePlannerProfile,
    *,
    visual_bridge: bool,
) -> tuple[VisualEffect, str]:
    pool = list(effect_pool(strategy, category, visual_bridge=visual_bridge))
    rng.shuffle(pool)
    limit = profile.max_consecutive_same_effect
    banned: set[VisualEffect] = set()
    if len(previous) >= limit:
        tail = previous[-limit:]
        if len(set(tail)) == 1:
            banned.add(tail[-1])
    for effect in pool:
        if effect not in banned:
            return effect, f"effect_from_pool:{effect.value}"
    return pool[0], "effect_forced_repeat"


def select_transition(
    beat: VisualBeat,
    previous_category: ContentCategory | None,
    profile: ScenePlannerProfile,
) -> tuple[TransitionType, str]:
    if not profile.prefer_cut_transition:
        return TransitionType.cut, "cut_default"
    category = (
        beat.classification.primary_category
        if beat.classification
        else ContentCategory.generic
    )
    if beat.visual_bridge:
        return TransitionType.dip_to_black, "transition_visual_bridge"
    if category is ContentCategory.time_establishing and previous_category is not None:
        return TransitionType.crossfade, "transition_time_change"
    if (
        category is ContentCategory.location_establishing
        and previous_category is not None
        and previous_category is not ContentCategory.location_establishing
    ):
        return TransitionType.crossfade, "transition_location_change"
    return TransitionType.cut, "cut_default"


def select_mood(category: ContentCategory, *, visual_bridge: bool) -> Mood:
    if visual_bridge:
        return Mood.neutral
    return _MOOD.get(category, Mood.neutral)
