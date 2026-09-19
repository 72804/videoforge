from __future__ import annotations

from docprod.models.enums import AssetStrategy
from docprod.planning.models import ContentCategory, VisualBeat
from docprod.planning.profile import ScenePlannerProfile
from docprod.planning.visual_policy import CINEMATIC_PREFERRED, PREFERRED_EXPLICIT

PREFERRED = CINEMATIC_PREFERRED

# Archive photographic sources should not be swapped for fake graphics.
LOCKED_STRATEGIES = {
    AssetStrategy.archive_image,
    AssetStrategy.archive_video,
}

ALTERNATIVES: dict[AssetStrategy, tuple[AssetStrategy, ...]] = {
    AssetStrategy.stock_video: (
        AssetStrategy.stock_image,
        AssetStrategy.archive_video,
        AssetStrategy.ai_image,
    ),
    AssetStrategy.archive_video: (
        AssetStrategy.stock_video,
        AssetStrategy.archive_image,
        AssetStrategy.ai_image,
    ),
    AssetStrategy.archive_image: (
        AssetStrategy.stock_image,
        AssetStrategy.stock_video,
        AssetStrategy.ai_image,
    ),
    AssetStrategy.stock_image: (
        AssetStrategy.stock_video,
        AssetStrategy.ai_image,
    ),
    AssetStrategy.ai_image: (
        AssetStrategy.stock_video,
        AssetStrategy.archive_image,
        AssetStrategy.placeholder,
    ),
    AssetStrategy.ai_image_to_video: (
        AssetStrategy.ai_image,
        AssetStrategy.stock_video,
    ),
    AssetStrategy.generated_graphic: (
        AssetStrategy.stock_video,
        AssetStrategy.ai_image,
    ),
    AssetStrategy.document: (AssetStrategy.archive_image, AssetStrategy.stock_video),
    AssetStrategy.map: (AssetStrategy.stock_video, AssetStrategy.ai_image),
    AssetStrategy.placeholder: (
        AssetStrategy.stock_video,
        AssetStrategy.ai_image,
    ),
    AssetStrategy.text_card: (
        AssetStrategy.stock_video,
        AssetStrategy.ai_image,
    ),
}

MOTION_CATEGORIES = {
    ContentCategory.action,
    ContentCategory.crime,
    ContentCategory.danger,
    ContentCategory.vehicle,
}


def preferred_strategy(
    category: ContentCategory,
    *,
    visual_bridge: bool,
    explicit_explainer: bool = False,
) -> AssetStrategy:
    if visual_bridge:
        return AssetStrategy.placeholder
    if explicit_explainer:
        return PREFERRED_EXPLICIT[category]
    return PREFERRED[category]


def is_motion_candidate(beat: VisualBeat) -> bool:
    classification = beat.classification
    if classification is None or beat.visual_bridge:
        return False
    if classification.motion_score < 1:
        return False
    if classification.primary_category in MOTION_CATEGORIES:
        return True
    return ContentCategory.action in classification.matched_categories


def allocate_ai_video(
    beats: list[VisualBeat],
    strategies: list[AssetStrategy],
    reasons: list[str],
    profile: ScenePlannerProfile,
) -> tuple[list[AssetStrategy], list[str]]:
    """Upgrade motion candidates to ai_image_to_video under a duration budget."""
    total = sum(beat.duration for beat in beats) or 1.0
    budget = profile.max_ai_video_fraction * total
    ranked = [
        index
        for index, beat in enumerate(beats)
        if is_motion_candidate(beat)
    ]
    ranked.sort(
        key=lambda index: (
            -(
                beats[index].classification.motion_strength
                if beats[index].classification
                else 0
            ),
            -(
                beats[index].classification.motion_score
                if beats[index].classification
                else 0
            ),
            index,
        )
    )
    selected: set[int] = set()
    remaining = budget
    for index in ranked:
        duration = beats[index].duration
        if duration > remaining + 1e-9:
            continue
        if _ai_video_run_too_long(selected, index, profile.max_consecutive_ai_video):
            continue
        selected.add(index)
        remaining -= duration

    result = list(strategies)
    result_reasons = list(reasons)
    for index, beat in enumerate(beats):
        if index in selected:
            result[index] = AssetStrategy.ai_image_to_video
            result_reasons[index] = "action_candidate_ai_video_budget_allowed"
        elif is_motion_candidate(beat):
            result[index] = AssetStrategy.ai_image
            if _ai_video_run_too_long(selected, index, profile.max_consecutive_ai_video):
                result_reasons[index] = "action_candidate_ai_video_consecutive_limit"
            else:
                result_reasons[index] = "action_candidate_ai_video_over_budget"
        beat.metadata["ai_video_budget_seconds"] = round(budget, 4)
    return result, result_reasons


def _ai_video_run_too_long(selected: set[int], index: int, max_run: int) -> bool:
    left = index - 1
    left_run = 0
    while left in selected:
        left_run += 1
        left -= 1
    right = index + 1
    right_run = 0
    while right in selected:
        right_run += 1
        right += 1
    return left_run + 1 + right_run > max_run


def apply_strategy_variety(
    strategies: list[AssetStrategy],
    reasons: list[str],
    profile: ScenePlannerProfile,
) -> tuple[list[AssetStrategy], list[str]]:
    """Soft cap on consecutive identical strategies. Semantics still win."""
    result = list(strategies)
    result_reasons = list(reasons)
    run_of = 1
    for index in range(1, len(result)):
        if result[index] == result[index - 1]:
            run_of += 1
        else:
            run_of = 1
        if run_of <= profile.max_consecutive_same_strategy:
            continue
        if result[index] in LOCKED_STRATEGIES:
            result_reasons[index] = f"{result_reasons[index]};variety_skipped_semantic_lock"
            continue
        swapped = False
        for alt in ALTERNATIVES.get(result[index], ()):
            if alt == result[index - 1]:
                continue
            result[index] = alt
            result_reasons[index] = f"{result_reasons[index]};variety_strategy_fallback"
            run_of = 1
            swapped = True
            break
        if not swapped:
            result_reasons[index] = f"{result_reasons[index]};variety_no_alternative"
    return result, result_reasons
