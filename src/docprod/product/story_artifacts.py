from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from docprod.product.episode import (
    EpisodeBrief,
    EpisodeShotPlan,
    LocationBible,
    ShotRequirement,
)
from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec, SceneBeatSpec
from docprod.product.production_director import (
    incomplete_generated_text,
    synthesize_final_story,
    unique_ids,
)
from docprod.quality.ensemble import ENSEMBLE_STAGES, CreativeEnsembleRun, EnsembleStageRecord
from docprod.quality.enums import SceneProductionClass


def output_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stage_output_text(run: CreativeEnsembleRun, stage_id: str) -> str:
    if stage_id.startswith("treatment_"):
        index = int(stage_id.rsplit("_", 1)[-1]) - 1
        if 0 <= index < len(run.treatments):
            return str(run.treatments[index] or "")
        return ""
    if stage_id == "critic":
        return run.critic_output
    if stage_id == "finalizer":
        return run.final_script
    return ""


def hydrate_succeeded_stages(run: CreativeEnsembleRun, *, model_id: str = "gpt-6-astra") -> None:
    usage = {item.call_id: item for item in run.model_usage}
    by_id = {item.stage_id: item for item in run.stages}
    for stage_id in ENSEMBLE_STAGES:
        text = stage_output_text(run, stage_id)
        if not text.strip():
            continue
        record = by_id.get(stage_id)
        used = usage.get(stage_id)
        if record is None:
            record = EnsembleStageRecord(stage_id=stage_id, model_id=model_id)
            run.stages.append(record)
            by_id[stage_id] = record
        record.model_id = (used.model_id if used else model_id) or model_id
        record.state = "SUCCEEDED"
        record.output_length = len(text)
        record.output_hash = output_sha256(text)
        if used:
            record.input_tokens = used.input_tokens
            record.output_tokens = used.output_tokens
            record.usd = used.usd
            record.request_id = used.request_id
            record.response_id = used.response_id
            record.request_fingerprint = used.request_fingerprint


def _parse_json_blob(text: str) -> dict[str, Any]:
    blob = text.strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*", "", blob)
        blob = re.sub(r"\s*```$", "", blob)
    return json.loads(blob)


def parse_friend_group_story(
    run: CreativeEnsembleRun,
    brief: EpisodeBrief,
) -> FriendGroupStorySpec:
    payload = _parse_json_blob(run.final_script)
    title = str(payload.get("title") or brief.title or "Episode")
    scenes = list(payload.get("scenes") or [])
    beats: list[SceneBeatSpec] = []
    lines: list[DialogueLineSpec] = []
    first_line = ""
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or f"S{index + 1}")
        shots = list(scene.get("shots") or [])
        visual = " ".join(
            str(shot.get("action") or "") for shot in shots if isinstance(shot, dict)
        ).strip()
        if incomplete_generated_text(visual):
            raise ValueError(f"scene {scene_id} description is incomplete: {visual[-48:]}")
        present: list[str] = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            for item in list(shot.get("dialogue") or []):
                if not isinstance(item, dict):
                    continue
                speaker = str(item.get("character") or "")
                text = str(item.get("line") or "")
                folded_speaker = unique_ids([speaker])
                if speaker and speaker not in present:
                    present.append(speaker)
                if text and not first_line:
                    first_line = text
                if text:
                    lines.append(
                        DialogueLineSpec(
                            speaker_character_id=folded_speaker[0]
                            if folded_speaker
                            else "unknown",
                            text=text,
                            emotion="",
                            delivery=str(item.get("delivery") or ""),
                            scene_id=scene_id,
                        )
                    )
        beats.append(
            SceneBeatSpec(
                scene_id=scene_id,
                order_index=index,
                hook=first_line if index == 0 else "",
                visual=visual,
                intent=str(scene.get("time") or ""),
                character_ids=unique_ids(present),
                duration_seconds=0.0,
            )
        )
    duration = float(payload.get("duration_seconds") or 59)
    notes = [str(item) for item in list(payload.get("production_notes") or [])]
    final_story = synthesize_final_story(payload, brief)
    if final_story.strip() == brief.premise.strip() and any(beat.visual for beat in beats):
        final_story = " ".join(beat.visual for beat in beats if beat.visual)
    return FriendGroupStorySpec(
        title=title,
        logline=str(payload.get("tone") or ""),
        cold_open_hook=first_line,
        premise=brief.premise,
        final_story=final_story,
        target_duration=duration,
        cast=list(payload.get("cast") or brief.cast_names),
        scene_beats=beats,
        dialogue_lines=lines,
        narration_lines=[],
        comedy_drama_tension=str(payload.get("tone") or ""),
        callbacks=[line.text for line in lines[:1] + lines[-1:]] if lines else [],
        payoff=brief.ending,
        ending=brief.ending,
        continuity_updates=notes,
        motion_graphics_requests=["phone invitation graphic"],
        audio_intent="cafe ambience, payment beep, no extra sting after the bite",
        estimated_duration=duration,
        engine_generated=True,
    )


def shot_plan_from_finalizer(payload: dict[str, Any]) -> EpisodeShotPlan:
    shots: list[ShotRequirement] = []
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "")
        for shot in list(scene.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            dialogue = list(shot.get("dialogue") or [])
            action = str(shot.get("action") or "")
            production = SceneProductionClass.MULTI_REFERENCE_SCENE.value
            if shot.get("on_screen_text"):
                production = SceneProductionClass.POST_PRODUCTION_MOTION_GRAPHICS.value
            elif "dış" in str(scene.get("location") or "").casefold() or "bankta" in action:
                production = SceneProductionClass.STATIC_KEYFRAME.value
            elif dialogue:
                production = SceneProductionClass.DIALOGUE_COVERAGE.value
            speakers = [
                str(item.get("character") or "").casefold()
                for item in dialogue
                if isinstance(item, dict)
            ]
            shots.append(
                ShotRequirement(
                    shot_id=str(shot.get("shot_id") or ""),
                    scene_id=scene_id,
                    production_class=production,
                    cast_refs=[name for name in speakers if name],
                    action=action,
                    framing=str(shot.get("framing") or ""),
                    preferred_model="seedance-2.5-reference-to-video",
                    fallback_model="runway-gen-4.5",
                    implementation_status="CATALOG_ONLY",
                    identity_required=True,
                )
            )
    return EpisodeShotPlan(shots=shots, engine_owned=True)


def location_bible_from_story(brief: EpisodeBrief) -> LocationBible:
    return LocationBible(
        name=brief.location or "Krispy Kreme café",
        interior_layout="Group table facing the entrance and window wall; counter behind.",
        tables="One occupied six-top with leftover boxes and drinks.",
        counter="Visible in the background; POS brought to the table.",
        windows="Street-facing glass connecting interior argument to exterior bench.",
        entrance="Door behind HG's sightline so Birko can slip out.",
        exterior="Bench immediately outside the same window.",
        lighting="Warm café interior; cooler evening street light outside.",
        time_of_day="evening",
        props=["receipt", "premium donut box", "water bottle", "POS", "phone", "last donut"],
        spatial_layout={
            "table": "One occupied six-top; same seats through interior scenes.",
            "counter": "Behind the table, opposite the window wall.",
            "window": "Street-facing glass on the table's window side.",
            "door": "Entrance behind HG's sightline so an exit can pass unseen by most.",
            "exterior_bench": "Bench immediately outside the same window.",
            "lighting": "Warm café interior; cooler evening street light outside.",
            "time_of_day": "evening",
        },
        engine_owned_details=False,
    )


def prop_ledger() -> list[str]:
    return [
        "3.840 TL receipt / bill — introduced at the table, stays with Kemal",
        "premium/special donut box — ordered after HG's prompt; empty at the end",
        "Kemal's small water bottle — visual contrast with the feast",
        "phones — Birko invitations, later Kemal's call",
        "POS terminal — Kemal pays",
        "last donut — revealed with Birko outside",
    ]


def format_generated_review(
    *,
    brief: EpisodeBrief,
    spec: FriendGroupStorySpec,
    shots: EpisodeShotPlan,
    location: LocationBible,
    voices: list[str],
    refs: list[str],
    known_usd: float,
    completed_calls: int,
    planned_calls: int,
) -> str:
    dialogue = [
        f"- [{line.scene_id}] {line.speaker_character_id}: {line.text}"
        + (f" ({line.delivery})" if line.delivery else "")
        for line in spec.dialogue_lines
    ]
    beats = [
        f"- {beat.scene_id} ({beat.duration_seconds:.1f}s): {beat.visual}"
        for beat in spec.scene_beats
    ]
    shot_lines = [
        f"- {shot.shot_id} class={shot.production_class} "
        f"visible={','.join(shot.visible_cast or shot.cast_refs) or 'none'} "
        f"offscreen={','.join(shot.offscreen_speakers) or 'none'} "
        f"executable={shot.executable_model or shot.preferred_model} "
        f"ideal={shot.ideal_model or shot.preferred_model} "
        f"status={shot.implementation_status} | {shot.action}"
        for shot in shots.shots
    ]
    return "\n".join(
        [
            "# Birko Episode 2 — Story Review",
            "",
            "Status: STORY GENERATED FROM CHECKPOINT. MEDIA NOT GENERATED.",
            "Ensemble: Astra treatments → fresh Astra critic → Astra finalizer.",
            f"completed_text_model_calls={completed_calls}",
            f"planned_text_model_calls={planned_calls}",
            f"known_usage_usd={known_usd:.5f}",
            "",
            "## TITLE",
            "",
            spec.title,
            "",
            "## LOGLINE",
            "",
            spec.logline or spec.comedy_drama_tension,
            "",
            "## HOOK",
            "",
            spec.cold_open_hook,
            "",
            "## CAST",
            "",
            ", ".join(spec.cast),
            "",
            "## FINAL STORY",
            "",
            spec.final_story or spec.premise,
            "",
            spec.payoff,
            "",
            f"Ending: {spec.ending}",
            "",
            "## SCENE BREAKDOWN",
            "",
            *beats,
            "",
            "## ALL DIALOGUE",
            "",
            *dialogue,
            "",
            "## NARRATION",
            "",
            *(spec.narration_lines or ["None. Dialogue-first."]),
            "",
            "## SHOT PLAN",
            "",
            *shot_lines,
            "",
            "## VOICE ASSIGNMENTS (proposed, TTS not called)",
            "",
            *voices,
            "",
            "## LOCATION BIBLE",
            "",
            f"name={location.name}",
            f"interior={location.interior_layout}",
            f"tables={location.tables}",
            f"counter={location.counter}",
            f"windows={location.windows}",
            f"entrance={location.entrance}",
            f"exterior={location.exterior}",
            f"lighting={location.lighting}",
            f"time_of_day={location.time_of_day}",
            "",
            "## PROP CONTINUITY",
            "",
            *[f"- {item}" for item in location.props or prop_ledger()],
            "",
            "## MODEL REQUIREMENTS PER SHOT",
            "",
            *shot_lines,
            "",
            "## EXPECTED DURATION",
            "",
            f"{spec.estimated_duration:.0f}s (target {brief.target_duration_seconds[0]:.0f}–"
            f"{brief.target_duration_seconds[1]:.0f}s)",
            "",
            "## VISUAL CONTINUITY",
            "",
            *refs,
            "",
            "## STORY MODEL COST",
            "",
            "execute=true (checkpoint recovered; no new provider calls in this repair)",
            "image/video/audio calls=0",
            "Stars=0",
            "",
        ]
    ) + "\n"
