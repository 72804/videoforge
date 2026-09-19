from __future__ import annotations

from dataclasses import dataclass, replace

from docprod.audio.script import tokenize_display
from docprod.exceptions import SemanticPlannerError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.planning.planner import image_prompt_for, motion_prompt_for
from docprod.planning.profile import STORY_DOCUMENTARY_V1, ScenePlannerProfile
from docprod.planning.semantic_models import (
    STORY_WORDS_PER_MINUTE,
    SemanticIntentSet,
    SemanticSceneIntent,
    StoryPlanDiagnostics,
)
from docprod.planning.semantic_validation import (
    diversity_warnings,
    hallucination_warnings,
    named_people,
    repetition_warnings,
)
from docprod.planning.visual_policy import (
    cinematic_strategy_for_intent,
    explicit_explainer_requested,
)
from docprod.research.models import ResearchDossier
from docprod.writing.models import NarrationScript

PREFERRED_SECONDS = (3.0, 5.0)
ALLOWED_SECONDS = (2.0, 7.0)
EMPHASIS_MIN = 1.5
ESTABLISH_MAX = 8.0
TARGET_SECONDS = 4.0


@dataclass
class _Draft:
    intent: SemanticSceneIntent
    start_word: int
    end_word: int
    narration: str
    duration: float
    strategy: AssetStrategy
    movement: str
    chapter: str


def compile_semantic_plan(
    intent_set: SemanticIntentSet,
    *,
    script: NarrationScript,
    dossier: ResearchDossier,
    profile: ScenePlannerProfile | None = None,
    words_per_minute: float = STORY_WORDS_PER_MINUTE,
) -> tuple[ScenePlan, StoryPlanDiagnostics]:
    cfg = profile or STORY_DOCUMENTARY_V1
    words = tokenize_display(script.full_narration)
    if not words:
        raise SemanticPlannerError("Script has no words to plan")
    repaired = _repair_spans(intent_set.intents, len(words))
    drafts = _split_and_time(repaired, words, words_per_minute)
    drafts = _merge_short(drafts, words, words_per_minute)
    if not drafts:
        raise SemanticPlannerError("Compiler produced no scenes")
    _validate_word_coverage(drafts, len(words))
    drafts = _allocate_ai_video(drafts, cfg)
    plan, diagnostics = _materialize(drafts, script, dossier, cfg, words_per_minute)
    return plan, diagnostics


def _repair_spans(intents: list[SemanticSceneIntent], word_count: int) -> list[SemanticSceneIntent]:
    ordered = sorted(intents, key=lambda item: (item.narration_start_word, item.narration_end_word))
    cursor = 0
    fixed: list[SemanticSceneIntent] = []
    for item in ordered:
        start = max(0, min(item.narration_start_word, word_count))
        end = max(0, min(item.narration_end_word, word_count))
        if end <= start:
            continue
        if start > cursor:
            start = cursor
        if start < cursor:
            start = cursor
        if end <= start:
            continue
        fixed.append(
            item.model_copy(update={"narration_start_word": start, "narration_end_word": end})
        )
        cursor = end
    if not fixed:
        raise SemanticPlannerError("Intents did not cover any narration words")
    if cursor < word_count:
        last = fixed[-1]
        fixed[-1] = last.model_copy(update={"narration_end_word": word_count})
    if fixed[0].narration_start_word > 0:
        first = fixed[0]
        fixed[0] = first.model_copy(update={"narration_start_word": 0})
    return fixed


def _split_and_time(
    intents: list[SemanticSceneIntent],
    words: list[str],
    wpm: float,
) -> list[_Draft]:
    drafts: list[_Draft] = []
    for intent in intents:
        start = intent.narration_start_word
        end = intent.narration_end_word
        establishing = intent.preferred_source_type in {
            "map",
            "document",
            "newspaper",
            "infographic",
            "archive",
        }
        max_words = _words_for_seconds(ESTABLISH_MAX if establishing else 5.0, wpm)
        target_words = _words_for_seconds(TARGET_SECONDS, wpm)
        cursor = start
        while cursor < end:
            remaining = end - cursor
            if remaining <= max_words:
                take = remaining
            else:
                take = min(target_words, remaining)
                leftover = remaining - take
                min_keep = _words_for_seconds(EMPHASIS_MIN, wpm)
                if 0 < leftover < min_keep:
                    take = remaining // 2
            chunk_end = cursor + take
            narration = " ".join(words[cursor:chunk_end])
            duration = round(take / wpm * 60.0, 4)
            strategy = map_strategy(intent)
            drafts.append(
                _Draft(
                    intent=intent,
                    start_word=cursor,
                    end_word=chunk_end,
                    narration=narration,
                    duration=duration,
                    strategy=strategy,
                    movement=intent.movement_need,
                    chapter=intent.chapter,
                )
            )
            cursor = chunk_end
    return drafts


def _merge_short(drafts: list[_Draft], words: list[str], wpm: float) -> list[_Draft]:
    if not drafts:
        return drafts
    merged: list[_Draft] = []
    for draft in drafts:
        if (
            merged
            and draft.duration < ALLOWED_SECONDS[0]
            and merged[-1].intent.intent_id == draft.intent.intent_id
            and merged[-1].duration + draft.duration <= ESTABLISH_MAX
        ):
            prev = merged[-1]
            end = draft.end_word
            narration = " ".join(words[prev.start_word : end])
            duration = round((end - prev.start_word) / wpm * 60.0, 4)
            merged[-1] = replace(prev, end_word=end, narration=narration, duration=duration)
        else:
            merged.append(draft)
    return merged


def _validate_word_coverage(drafts: list[_Draft], word_count: int) -> None:
    cursor = 0
    for draft in drafts:
        if draft.start_word != cursor:
            raise SemanticPlannerError(
                f"Narration span gap/overlap at word {cursor} vs {draft.start_word}"
            )
        if draft.end_word <= draft.start_word:
            raise SemanticPlannerError("Empty narration span")
        cursor = draft.end_word
    if cursor != word_count:
        raise SemanticPlannerError(f"Spans cover {cursor} words, expected {word_count}")


def map_strategy(intent: SemanticSceneIntent) -> AssetStrategy:
    if not explicit_explainer_requested(intent):
        return cinematic_strategy_for_intent(intent)
    pref = intent.preferred_source_type
    if intent.historical_specificity == "exact_person_or_event":
        if pref in {"document", "newspaper"}:
            return AssetStrategy.document
        if pref == "map":
            return AssetStrategy.map
        return AssetStrategy.archive_image
    if pref == "archive":
        if intent.movement_need in {"medium", "high"}:
            return AssetStrategy.archive_video
        return AssetStrategy.archive_image
    if pref == "photograph":
        return AssetStrategy.archive_image
    if pref == "stock_video":
        return AssetStrategy.stock_video
    if pref in {"document", "newspaper"}:
        return AssetStrategy.document
    if pref == "map":
        return AssetStrategy.map
    if pref == "infographic":
        return AssetStrategy.generated_graphic
    if pref == "text_card":
        return AssetStrategy.text_card
    if pref == "ai_reenactment":
        if intent.reenactment_freedom == "avoid":
            return AssetStrategy.stock_video
        return AssetStrategy.ai_image
    return AssetStrategy.stock_video


def _allocate_ai_video(drafts: list[_Draft], profile: ScenePlannerProfile) -> list[_Draft]:
    total = sum(item.duration for item in drafts) or 1.0
    cap = min(profile.max_ai_video_fraction, 0.10) * total
    ranked = [
        index
        for index, item in enumerate(drafts)
        if item.strategy is AssetStrategy.ai_image and item.movement == "high"
    ]
    selected: set[int] = set()
    remaining = cap
    for index in ranked:
        duration = drafts[index].duration
        if duration > remaining + 1e-9:
            continue
        if _run_too_long(selected, index, profile.max_consecutive_ai_video):
            continue
        selected.add(index)
        remaining -= duration
    out: list[_Draft] = []
    for index, item in enumerate(drafts):
        if index in selected:
            out.append(replace(item, strategy=AssetStrategy.ai_image_to_video))
        else:
            out.append(item)
    return out


def _run_too_long(selected: set[int], index: int, max_run: int) -> bool:
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


def _materialize(
    drafts: list[_Draft],
    script: NarrationScript,
    dossier: ResearchDossier,
    profile: ScenePlannerProfile,
    wpm: float,
) -> tuple[ScenePlan, StoryPlanDiagnostics]:
    scenes: list[Scene] = []
    t = 0.0
    hallu: list = []
    people = {name.casefold() for name in named_people(dossier)}
    named_archive = 0
    reenactments = 0
    for index, draft in enumerate(drafts):
        intent = draft.intent
        duration = _clamp_duration(draft.duration, draft.strategy)
        start = round(t, 4)
        end = round(t + duration, 4)
        t = end
        scene_id = f"scene_{index + 1:04d}"
        visual_intent = _visual_intent(intent, draft.strategy)
        generation = GenerationSpec()
        if draft.strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
            seed = intent.image_prompt_seed or visual_intent
            generation = GenerationSpec(
                image_prompt=image_prompt_for(seed),
                motion_prompt=(
                    motion_prompt_for(intent.visual_action, [])
                    if draft.strategy is AssetStrategy.ai_image_to_video
                    else None
                ),
                seed=index + 1,
            )
            reenactments += 1
        if draft.strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}:
            if any(name in (intent.visual_subject or "").casefold() for name in people):
                named_archive += 1
        effect = _effect(draft.strategy)
        mood = _mood(draft.strategy, intent)
        metadata = {
            "planner_version": profile.planner_version,
            "planner_profile": profile.name,
            "semantic_intent_id": intent.intent_id,
            "preferred_source_type": intent.preferred_source_type,
            "movement_need": intent.movement_need,
            "historical_specificity": intent.historical_specificity,
            "reenactment_freedom": intent.reenactment_freedom,
            "reenactment_type": intent.reenactment_type,
            "continuity_entities": list(intent.continuity_entities),
            "claim_ids": list(intent.claim_ids),
            "source_ids": list(intent.source_ids),
            "visual_subject": intent.visual_subject,
            "visual_action": intent.visual_action,
            "visual_environment": intent.visual_environment,
            "visual_purpose": intent.visual_purpose,
            "visual_description": intent.visual_description,
            "image_prompt_seed": intent.image_prompt_seed,
            "stock_query_seed": intent.stock_query_seed,
            "archive_search_seed": intent.archive_search_seed,
            "graphic_brief": intent.graphic_brief,
            "explicit_explainer": intent.explicit_explainer,
            "reasoning_summary": intent.reasoning_summary,
            "chapter": intent.chapter,
            "narration_start_word": draft.start_word,
            "narration_end_word": draft.end_word,
            "estimated_wpm": wpm,
            "archive_unresolved": draft.strategy
            in {AssetStrategy.archive_image, AssetStrategy.archive_video},
            "stylized_graphic_not_authentic": draft.strategy
            in {AssetStrategy.document, AssetStrategy.generated_graphic, AssetStrategy.map}
            and explicit_explainer_requested(intent),
        }
        flags = hallucination_warnings(
            scene_id=scene_id,
            intent=intent,
            strategy=draft.strategy,
            dossier=dossier,
            script=script,
        )
        if flags:
            metadata["hallucination_warnings"] = [item.model_dump() for item in flags]
            hallu.extend(flags)
        scenes.append(
            Scene(
                id=scene_id,
                start=start,
                end=end,
                duration=round(end - start, 4),
                narration=draft.narration,
                visual_intent=visual_intent,
                asset_strategy=draft.strategy,
                effect=effect,
                transition=TransitionType.cut,
                mood=mood,
                subtitle=draft.narration,
                generation=generation,
                sources=[],
                metadata=metadata,
            )
        )
    plan = ScenePlan(
        project_id=script.project_id,
        scenes=scenes,
        total_duration=scenes[-1].end if scenes else 0.0,
    )
    strategies = [scene.asset_strategy for scene in scenes]
    subjects = [str(scene.metadata.get("visual_subject") or "") for scene in scenes]
    reps = repetition_warnings(subjects, strategies)
    divs = diversity_warnings(strategies)
    durations = [scene.duration for scene in scenes]
    coverage = sum(durations)
    counts: dict[str, int] = {}
    for scene in scenes:
        key = scene.asset_strategy.value
        counts[key] = counts.get(key, 0) + 1
    ai_video = sum(
        scene.duration
        for scene in scenes
        if scene.asset_strategy is AssetStrategy.ai_image_to_video
    )
    diagnostics = StoryPlanDiagnostics(
        scene_count=len(scenes),
        estimated_runtime_seconds=round(coverage, 4),
        average_scene_duration=round(coverage / len(durations), 4) if durations else 0.0,
        min_scene_duration=round(min(durations), 4) if durations else 0.0,
        max_scene_duration=round(max(durations), 4) if durations else 0.0,
        strategy_counts=dict(sorted(counts.items())),
        ai_video_seconds=round(ai_video, 4),
        ai_video_fraction=round(ai_video / coverage, 6) if coverage else 0.0,
        archive_opportunities=counts.get("archive_image", 0) + counts.get("archive_video", 0),
        stock_scenes=counts.get("stock_video", 0) + counts.get("stock_image", 0),
        ai_still_scenes=counts.get("ai_image", 0),
        ai_video_scenes=counts.get("ai_image_to_video", 0),
        map_scenes=counts.get("map", 0),
        document_scenes=counts.get("document", 0),
        graphic_scenes=counts.get("generated_graphic", 0) + counts.get("text_card", 0),
        reenactment_count=reenactments,
        named_person_archive_opportunities=named_archive,
        claims_referenced=len(
            {cid for scene in scenes for cid in scene.metadata.get("claim_ids") or []}
        ),
        sources_referenced=len(
            {sid for scene in scenes for sid in scene.metadata.get("source_ids") or []}
        ),
        repetition_warnings=reps,
        hallucination_warnings=hallu,
        diversity_warnings=divs,
    )
    if diagnostics.ai_video_fraction > 0.10 + 1e-9:
        raise SemanticPlannerError(
            f"AI-video fraction {diagnostics.ai_video_fraction} exceeds 0.10 cap"
        )
    return plan, diagnostics


def _clamp_duration(duration: float, strategy: AssetStrategy) -> float:
    establishing = strategy in {
        AssetStrategy.map,
        AssetStrategy.document,
        AssetStrategy.generated_graphic,
        AssetStrategy.archive_image,
        AssetStrategy.archive_video,
    }
    high = ESTABLISH_MAX if establishing else ALLOWED_SECONDS[1]
    low = EMPHASIS_MIN
    return round(min(high, max(low, duration)), 4)


def _visual_intent(intent: SemanticSceneIntent, strategy: AssetStrategy) -> str:
    parts = [
        intent.visual_description,
        intent.visual_subject,
        intent.visual_action,
        intent.visual_environment,
        intent.visual_purpose,
    ]
    text = ". ".join(part.strip() for part in parts if part and part.strip())
    if not text:
        text = intent.narration_span or "Documentary visual"
    if strategy in {AssetStrategy.document, AssetStrategy.generated_graphic}:
        text = f"{text}. Stylized documentary graphic summary, not a fake authentic record."
    if strategy is AssetStrategy.map and "schematic" not in text.lower():
        text = f"{text}. Schematic geography; not an exact unsourced transport route."
    if strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}:
        text = f"{text}. Planned archive/historical source; unresolved until retrieval exists."
    return text.strip()


def _effect(strategy: AssetStrategy) -> VisualEffect:
    if strategy is AssetStrategy.map:
        return VisualEffect.map_route
    if strategy is AssetStrategy.document:
        return VisualEffect.newspaper_reveal
    if strategy is AssetStrategy.generated_graphic:
        return VisualEffect.location_date_card
    if strategy in {
        AssetStrategy.stock_video,
        AssetStrategy.archive_video,
        AssetStrategy.ai_image_to_video,
    }:
        return VisualEffect.documentary_handheld
    return VisualEffect.slow_push_in


def _mood(strategy: AssetStrategy, intent: SemanticSceneIntent) -> Mood:
    if strategy is AssetStrategy.document:
        return Mood.tense
    if strategy is AssetStrategy.map:
        return Mood.mysterious
    if "court" in (intent.visual_purpose or "").lower():
        return Mood.tense
    return Mood.neutral


def _words_for_seconds(seconds: float, wpm: float) -> int:
    return max(1, int(round(seconds * wpm / 60.0)))
