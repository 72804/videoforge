from __future__ import annotations

from docprod.audio.script import tokenize_display
from docprod.drama.story import BEATS, WORDS_PER_MINUTE, DramaBeatSpec
from docprod.drama.uniqueness import assert_unique_cinematic_visuals, scene_visual_fingerprint
from docprod.models.enums import AssetStrategy
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.quality.classify import DRAMA_BEAT_CLASS
from docprod.writing.models import NarrationScript

TITLE_SECONDS = 1.1
MIN_BEAT_SECONDS = 3.5
MAX_BEAT_SECONDS = 6.0
HARD_MAX_BEAT_SECONDS = 7.1
STILL_NEGATIVE = (
    "collage, storyboard, split-screen, split image, 2x2 grid, 3x3 grid, "
    "contact sheet, photo grid, infographic, fake UI, fake newspaper, "
    "embedded readable text, multiple panels, extra crowd"
)


def _beat_duration(beat: DramaBeatSpec) -> float:
    if beat.title_card:
        return TITLE_SECONDS
    words = len(tokenize_display(beat.narration))
    raw = max(MIN_BEAT_SECONDS, round(60.0 * words / WORDS_PER_MINUTE, 3))
    if raw > HARD_MAX_BEAT_SECONDS:
        raise ValueError(
            f"{beat.beat_id} would hold a still for {raw:.2f}s; split the narration"
        )
    return raw


def compile_drama_scene_plan(script: NarrationScript) -> ScenePlan:
    scenes: list[Scene] = []
    cursor = 0.0
    index = 1
    for beat in BEATS:
        duration = _beat_duration(beat)
        start = round(cursor, 4)
        end = round(cursor + duration, 4)
        title = beat.title_card
        if title:
            scene = Scene(
                id=f"scene_{index:04d}",
                start=start,
                end=end,
                duration=round(end - start, 4),
                narration="",
                visual_intent=beat.visual_intent,
                asset_strategy=AssetStrategy.text_card,
                effect=beat.effect,
                transition=beat.transition,
                mood=beat.mood,
                subtitle=title,
                generation=GenerationSpec(negative_prompt=STILL_NEGATIVE),
                sources=[],
                metadata={
                    "visual_bridge": True,
                    "cinematic_title_card": True,
                    "chapter": beat.chapter_id,
                    "chapter_title": title,
                    "beat_id": beat.beat_id,
                    "asset_unit_id": f"au_title_{index:02d}",
                    "primary_category": "generic",
                    "runtime_preview_strategy": "title_card",
                },
            )
        else:
            scene = Scene(
                id=f"scene_{index:04d}",
                start=start,
                end=end,
                duration=round(end - start, 4),
                narration=beat.narration,
                visual_intent=beat.visual_intent,
                asset_strategy=AssetStrategy.ai_image,
                effect=beat.effect,
                transition=beat.transition,
                mood=beat.mood,
                subtitle=beat.narration,
                generation=GenerationSpec(
                    image_prompt=beat.image_prompt,
                    negative_prompt=STILL_NEGATIVE,
                    seed=1000 + index,
                ),
                sources=[],
                metadata={
                    "chapter": beat.chapter_id,
                    "beat_id": beat.beat_id,
                    "asset_unit_id": f"au_{beat.beat_id}",
                    "primary_category": "interior"
                    if "interior" in beat.image_prompt or "kitchen" in beat.image_prompt
                    else "generic",
                    "runtime_preview_strategy": "ai_keyframe_preview",
                    "episode_mode": "custom_short_drama",
                    "characters": list(beat.characters),
                    "character_ref_ids": [f"ref_{name}" for name in beat.characters],
                    "planned_sfx": beat.sfx or "",
                    "purpose": beat.purpose,
                    "production_class_hint": DRAMA_BEAT_CLASS.get(beat.beat_id, "").value
                    if beat.beat_id in DRAMA_BEAT_CLASS
                    else "",
                },
            )
        scene.metadata["visual_fingerprint"] = scene_visual_fingerprint(scene)
        scenes.append(scene)
        cursor = end
        index += 1
    plan = ScenePlan(
        project_id=script.project_id,
        scenes=scenes,
        total_duration=scenes[-1].end if scenes else 0.0,
    )
    assert_unique_cinematic_visuals(plan)
    return plan
