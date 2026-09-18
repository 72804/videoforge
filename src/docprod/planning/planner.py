from __future__ import annotations

import random
import re

from docprod.models.enums import AssetStrategy
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.models.script import NarrationScript
from docprod.planning.classifier import classify_text
from docprod.planning.effects import select_effect, select_mood, select_transition
from docprod.planning.models import ContentCategory, VisualBeat, round_time
from docprod.planning.profile import ScenePlannerProfile
from docprod.planning.segmentation import segment_script
from docprod.planning.strategy import (
    allocate_ai_video,
    apply_strategy_variety,
    preferred_strategy,
)

STILL_SUFFIX = (
    "cinematic documentary reenactment, realistic photography, "
    "natural lighting, 35mm documentary look, 16:9"
)

_INTENT = {
    ContentCategory.location_establishing: "Establishing documentary shot representing: {n}",
    ContentCategory.time_establishing: "Time-establishing graphic or insert representing: {n}",
    ContentCategory.person: "Documentary portrait representing: {n}",
    ContentCategory.money: "Documentary visual of money or value representing: {n}",
    ContentCategory.police: "Documentary visual related to police activity: {n}",
    ContentCategory.crime: "Documentary visual related to the described crime: {n}",
    ContentCategory.vehicle: "Documentary shot of the described vehicle or transit: {n}",
    ContentCategory.building: "Documentary shot of the described building: {n}",
    ContentCategory.document: "Documentary close-up of a document or record representing: {n}",
    ContentCategory.news: "Documentary insert of news or press material representing: {n}",
    ContentCategory.map_or_travel: "Documentary map or travel graphic representing: {n}",
    ContentCategory.technology: "Documentary visual of the described technology: {n}",
    ContentCategory.phone_or_computer: "Documentary visual of a phone or computer: {n}",
    ContentCategory.court_or_legal: "Documentary visual of legal or court material: {n}",
    ContentCategory.nature: "Documentary landscape representing: {n}",
    ContentCategory.crowd: "Documentary crowd or public-space shot representing: {n}",
    ContentCategory.interior: "Documentary interior representing: {n}",
    ContentCategory.action: "Documentary reenactment of the described action: {n}",
    ContentCategory.danger: "Documentary visual of the described danger: {n}",
    ContentCategory.generic: "Documentary visual representing: {n}",
}

_WALK = re.compile(r"walk|yürü|yuru", re.IGNORECASE)
_DRIVE = re.compile(r"drive|drove|sür|sur|araba", re.IGNORECASE)
_RUN = re.compile(r"run|ran|koş|kos|kaç|kac", re.IGNORECASE)


def concise_narration(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit(" ", 1)[0]


def visual_intent_for(beat: VisualBeat) -> str:
    if beat.visual_bridge:
        return "Documentary holding shot covering a pause in narration"
    category = (
        beat.classification.primary_category
        if beat.classification
        else ContentCategory.generic
    )
    snippet = concise_narration(beat.text)
    template = _INTENT.get(category, _INTENT[ContentCategory.generic])
    return template.format(n=snippet)


def image_prompt_for(intent: str) -> str:
    return f"{intent}. {STILL_SUFFIX}"


def motion_prompt_for(text: str, motion_terms: list[str]) -> str:
    blob = f"{text} {' '.join(motion_terms)}"
    if _RUN.search(blob):
        return "subject moves quickly through the space, subtle handheld documentary camera"
    if _WALK.search(blob):
        return "subject walks forward naturally, subtle handheld documentary camera"
    if _DRIVE.search(blob):
        return "vehicle motion through the scene, restrained documentary camera"
    return "subtle realistic subject motion, restrained handheld documentary camera movement"


def plan_scenes(
    *,
    project_id: str,
    script: NarrationScript,
    random_seed: int,
    profile: ScenePlannerProfile,
) -> ScenePlan:
    beats = segment_script(script, profile)
    for beat in beats:
        if beat.visual_bridge:
            beat.classification = classify_text("", script.language)
        else:
            beat.classification = classify_text(beat.text, script.language)

    strategies = []
    reasons = []
    for beat in beats:
        category = (
            beat.classification.primary_category
            if beat.classification
            else ContentCategory.generic
        )
        strategies.append(preferred_strategy(category, visual_bridge=beat.visual_bridge))
        if beat.visual_bridge:
            reasons.append("visual_bridge_placeholder")
        else:
            reasons.append(f"category_{category.value}")
    strategies, reasons = allocate_ai_video(beats, strategies, reasons, profile)
    strategies, reasons = apply_strategy_variety(strategies, reasons, profile)

    rng = random.Random(random_seed)
    scenes: list[Scene] = []
    previous_effects: list = []
    previous_category: ContentCategory | None = None
    for index, beat in enumerate(beats):
        category = (
            beat.classification.primary_category
            if beat.classification
            else ContentCategory.generic
        )
        strategy = strategies[index]
        local_rng = random.Random(rng.randint(0, 2**30) + index)
        effect, effect_reason = select_effect(
            strategy,
            category,
            previous_effects,
            local_rng,
            profile,
            visual_bridge=beat.visual_bridge,
        )
        transition, transition_reason = select_transition(beat, previous_category, profile)
        intent = visual_intent_for(beat)
        narration = beat.text.strip()
        subtitle = narration
        generation = GenerationSpec()
        if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
            motion_terms = beat.classification.motion_terms if beat.classification else []
            generation = GenerationSpec(
                image_prompt=image_prompt_for(intent),
                negative_prompt=None,
                motion_prompt=(
                    motion_prompt_for(narration, motion_terms)
                    if strategy is AssetStrategy.ai_image_to_video
                    else None
                ),
                seed=random_seed + index + 1,
            )
        metadata = {
            "planner_version": profile.planner_version,
            "planner_profile": profile.name,
            "source_utterance_ids": list(beat.source_utterance_ids),
            "primary_category": category.value,
            "matched_categories": [
                item.value
                for item in (
                    beat.classification.matched_categories if beat.classification else []
                )
            ],
            "matched_terms": list(beat.classification.matched_terms if beat.classification else []),
            "strategy_reason": reasons[index],
            "effect_reason": effect_reason,
            "transition_reason": transition_reason,
            "segmentation_reason": beat.segmentation_reason,
            "motion_score": beat.classification.motion_score if beat.classification else 0,
            "ai_video_budget_seconds": beat.metadata.get("ai_video_budget_seconds"),
        }
        if beat.visual_bridge:
            metadata["visual_bridge"] = True
        start = round_time(beat.start)
        end = round_time(beat.end)
        scenes.append(
            Scene(
                id=f"scene_{index + 1:04d}",
                start=start,
                end=end,
                duration=round_time(end - start),
                narration=narration if narration else "",
                visual_intent=intent,
                asset_strategy=strategy,
                effect=effect,
                transition=transition,
                mood=select_mood(category, visual_bridge=beat.visual_bridge),
                subtitle=subtitle,
                generation=generation,
                sources=[],
                metadata=metadata,
            )
        )
        previous_effects.append(effect)
        previous_category = category

    total = scenes[-1].end if scenes else 0.0
    return ScenePlan(project_id=project_id, scenes=scenes, total_duration=round_time(total))
