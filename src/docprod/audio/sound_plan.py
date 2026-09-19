from __future__ import annotations

from docprod.audio.models import RuntimeTimeline
from docprod.audio.sound_library import SoundLibrary
from docprod.audio.sound_models import (
    MusicSection,
    SonicProfile,
    SoundCue,
    SoundNeed,
    SoundPlan,
    TensionKnot,
    TimeSpan,
)
from docprod.models.scene import ScenePlan
from docprod.providers.pricing import MUSIC_HARD_MAX
from docprod.writing.models import NarrationScript


def default_sonic_profile() -> SonicProfile:
    return SonicProfile()


def build_sound_plan(
    *,
    project_id: str,
    timeline: RuntimeTimeline,
    scenes: ScenePlan,
    script: NarrationScript | None = None,
    library: SoundLibrary | None = None,
    matcher: str = "metadata",
    veo_candidates: dict[str, str] | None = None,
    profile: SonicProfile | None = None,
) -> SoundPlan:
    sonic = profile or default_sonic_profile()
    duration = float(timeline.total_duration or timeline.audio_duration)
    chapters = _chapter_spans(timeline, scenes, script)
    knots = _tension_knots(chapters, duration)
    needs = _sound_needs(chapters, knots, timeline, veo_candidates or {})
    sections = _music_sections(needs, chapters, duration)
    if len(sections) > MUSIC_HARD_MAX:
        sections = _merge_music_sections(sections, MUSIC_HARD_MAX)
    lib = library or SoundLibrary()
    cues: list[SoundCue] = []
    reused: list[str] = []
    generation_music = 0
    for section in sections:
        need = next(
            (item for item in needs if item.sound_need_id == section.music_section_id),
            None,
        )
        match = lib.match(need, matcher=matcher) if need and need.reuse_allowed else None
        if match is not None:
            section.library_asset_id = match.asset_id
            section.generation_required = False
            section.status = "reuse"
            reused.append(match.asset_id)
            generated_or_reused = "reused"
            asset_id = match.asset_id
        else:
            section.generation_required = True
            section.status = "generate"
            generation_music += 1
            generated_or_reused = "generate"
            asset_id = ""
        cues.append(
            SoundCue(
                cue_id=f"cue_{section.music_section_id}",
                sound_need_id=section.music_section_id,
                type="music",
                start=section.start,
                end=section.end,
                scene_ids=section.visual_context_scene_ids,
                asset_id=asset_id,
                source_type="MUSIC_BED",
                generated_or_reused=generated_or_reused,
                gain_db=-22.0,
                fade_in=1.6,
                fade_out=2.0,
                duck_under_voice=True,
                story_reason=section.purpose,
                license_or_generation_metadata="generated/generic underscore; not archival",
                status=section.status,
            )
        )
    for need in needs:
        if need.type == "music":
            continue
        if need.type == "silence":
            continue
        match = lib.match(need, matcher=matcher) if need.reuse_allowed else None
        generated_or_reused = "reused" if match else "local_generic"
        asset_id = match.asset_id if match else ""
        if match:
            reused.append(match.asset_id)
        if need.type == "ambience" and need.notes.startswith("veo:"):
            generated_or_reused = "veo_candidate"
            asset_id = need.notes.split("veo:", 1)[1]
        cues.append(
            SoundCue(
                cue_id=f"cue_{need.sound_need_id}",
                sound_need_id=need.sound_need_id,
                type=need.type,
                start=need.start,
                end=need.end,
                scene_ids=need.scene_ids,
                asset_id=asset_id,
                source_type=need.type.upper(),
                generated_or_reused=generated_or_reused,
                sync_required=need.sync_required,
                gain_db=-28.0 if need.type == "ambience" else -16.0,
                fade_in=0.3 if need.type != "event_sfx" else 0.02,
                fade_out=0.5 if need.type != "event_sfx" else 0.15,
                duck_under_voice=need.type != "event_sfx",
                story_reason=need.story_reason,
                license_or_generation_metadata="generated/generic; not archival event audio",
                status="planned",
            )
        )
    silence = [
        TimeSpan(start=item.start, end=item.end, reason=item.story_reason)
        for item in needs
        if item.type == "silence"
    ]
    ordered = sorted(sections, key=lambda item: item.start)
    cursor = 0.0
    for section in ordered:
        if section.start - cursor >= 8.0:
            silence.append(
                TimeSpan(
                    start=cursor,
                    end=section.start,
                    reason="Music withheld between incompatible story sections.",
                )
            )
        cursor = max(cursor, section.end)
    if duration - cursor >= 8.0:
        silence.append(
            TimeSpan(start=cursor, end=duration, reason="Closing speech room without underscore.")
        )
    if generation_music > MUSIC_HARD_MAX:
        raise RuntimeError(
            f"SoundPlan requires {generation_music} music generations; hard max is {MUSIC_HARD_MAX}"
        )
    return SoundPlan(
        project_id=project_id,
        duration=duration,
        sonic_profile=sonic,
        knots=knots,
        needs=needs,
        music_sections=sections,
        cues=cues,
        silence_spans=silence,
        reused_asset_ids=sorted(set(reused)),
        generation_required_music=generation_music,
        notes=[
            "Story decides music count; not a fixed three-track template.",
            "Silence is a valid deliberate result.",
            "Generated audio is never labeled archival.",
        ],
        paid_api_calls={"lyria_3_5": generation_music, "lyria_realtime": 0},
    )


def _chapter_spans(
    timeline: RuntimeTimeline,
    scenes: ScenePlan,
    script: NarrationScript | None,
) -> list[dict[str, object]]:
    meta = {scene.id: scene for scene in scenes.scenes}
    chapters_from_script = []
    if script is not None and script.outline.chapters:
        chapters_from_script = [item.title or item.chapter_id for item in script.outline.chapters]
    rows: list[dict[str, object]] = []
    current_name = ""
    current_items: list = []
    for timing in timeline.scenes:
        scene = meta.get(timing.scene_id)
        chapter = ""
        if scene is not None:
            chapter = str(scene.metadata.get("chapter") or "")
        if not chapter:
            chapter = _infer_chapter(timing.narration, timing.start, timeline.total_duration)
        chapter = _normalize_chapter(chapter)
        if current_items and chapter != current_name:
            rows.append(_span_row(current_name, current_items))
            current_items = []
        current_name = chapter
        current_items.append(timing)
    if current_items:
        rows.append(_span_row(current_name, current_items))
    if not rows and chapters_from_script:
        rows.append(_span_row("story", list(timeline.scenes)))
    return rows


def _span_row(name: str, items: list) -> dict[str, object]:
    return {
        "chapter": name,
        "start": min(item.start for item in items),
        "end": max(item.end for item in items),
        "scene_ids": [item.scene_id for item in items],
        "narration": " ".join(item.narration for item in items),
    }


def _infer_chapter(narration: str, start: float, duration: float) -> str:
    text = narration.casefold()
    if any(token in text for token in ("depo", "fıçı", "fici", "envanter", "şurup", "surup")):
        return "warehouse_discovery"
    if any(token in text for token in ("soruştur", "polis", "kanıt", "kanit", "araştır", "baskın")):
        return "investigation"
    if any(token in text for token in ("mahkeme", "dava", "hapis", "ceza", "mahkûm")):
        return "court_resolution"
    if any(token in text for token in ("milyon", "ton", "değer", "deger", "istatistik", "ölçek")):
        return "scale_and_facts"
    ratio = start / duration if duration else 0
    if ratio < 0.22:
        return "opening"
    if ratio < 0.55:
        return "investigation"
    if ratio < 0.78:
        return "scale_and_facts"
    return "resolution"


def _normalize_chapter(name: str) -> str:
    key = name.casefold()
    mapping = {
        "c001": "opening",
        "c002": "opening",
        "c003": "warehouse_discovery",
        "c004": "warehouse_discovery",
        "c005": "scale_and_facts",
        "c006": "investigation",
        "c007": "investigation",
        "c008": "court_resolution",
        "c009": "resolution",
        "c010": "resolution",
    }
    if key in mapping:
        return mapping[key]
    if "kanca" in key or "rezerv" in key:
        return "opening"
    if "depo" in key or "keşif" in key or "kesif" in key:
        return "warehouse_discovery"
    if "ölçek" in key or "olcek" in key or "kayıp" in key:
        return "scale_and_facts"
    if "soruştur" in key or "baskın" in key or "tutuk" in key:
        return "investigation"
    if "mahkeme" in key:
        return "court_resolution"
    if "kapan" in key or "güvenlik" in key or "guvenlik" in key:
        return "resolution"
    return name


def _tension_knots(chapters: list[dict[str, object]], duration: float) -> list[TensionKnot]:
    knots: list[TensionKnot] = []
    for item in chapters:
        start = float(item["start"])
        end = float(item["end"])
        name = str(item["chapter"])
        mid = (start + end) / 2
        tension, mystery, urgency, reflection, info, music, silence, state, reason = _curve(name)
        knots.append(
            TensionKnot(
                time=round(start, 3),
                chapter=name,
                story_state=state,
                tension=tension,
                mystery=mystery,
                urgency=urgency,
                reflection=reflection,
                information_density=info,
                music_need=music,
                silence_preference=silence,
                reason=reason,
            )
        )
        knots.append(
            TensionKnot(
                time=round(mid, 3),
                chapter=name,
                story_state=state,
                tension=min(1.0, tension + 0.08),
                mystery=mystery,
                urgency=urgency,
                reflection=reflection,
                information_density=info,
                music_need=music,
                silence_preference=silence,
                reason=reason,
            )
        )
        knots.append(
            TensionKnot(
                time=round(end, 3),
                chapter=name,
                story_state=state,
                tension=max(0.0, tension - 0.05),
                mystery=max(0.0, mystery - 0.05),
                urgency=urgency,
                reflection=min(1.0, reflection + 0.1),
                information_density=info,
                music_need=max(0.15, music - 0.1),
                silence_preference=min(1.0, silence + 0.05),
                reason=reason,
            )
        )
    if knots and knots[-1].time < duration:
        last = knots[-1]
        knots.append(last.model_copy(update={"time": round(duration, 3)}))
    return knots


def _curve(chapter: str) -> tuple[float, float, float, float, float, float, float, str, str]:
    key = chapter.casefold()
    if "open" in key or "warehouse" in key or "discovery" in key:
        return (0.55, 0.72, 0.35, 0.15, 0.35, 0.7, 0.2, "hook", "mystery around the warehouse find")
    if "invest" in key:
        return (0.62, 0.55, 0.58, 0.2, 0.45, 0.65, 0.25, "pursuit", "investigation pressure")
    if "fact" in key or "scale" in key:
        return (0.4, 0.25, 0.3, 0.35, 0.78, 0.28, 0.72, "exposition", "numbers need speech room")
    if "court" in key or "resol" in key:
        return (0.48, 0.2, 0.25, 0.7, 0.4, 0.55, 0.35, "aftermath", "reflective legal close")
    return (0.45, 0.4, 0.35, 0.3, 0.5, 0.5, 0.4, "narration", "story-following underscore")


def _sound_needs(
    chapters: list[dict[str, object]],
    _knots: list[TensionKnot],
    timeline: RuntimeTimeline,
    veo_candidates: dict[str, str],
) -> list[SoundNeed]:
    needs: list[SoundNeed] = []
    for index, chapter in enumerate(chapters):
        name = str(chapter["chapter"])
        start = float(chapter["start"])
        end = float(chapter["end"])
        scene_ids = list(chapter["scene_ids"])
        _t, _m, _u, _r, info, music, silence, _state, reason = _curve(name)
        if silence >= 0.65 and info >= 0.65:
            needs.append(
                SoundNeed(
                    sound_need_id=f"silence_{index:02d}",
                    start=start,
                    end=end,
                    scene_ids=scene_ids,
                    chapter=name,
                    type="silence",
                    story_reason="Dense factual narration; music would compete.",
                    importance="high",
                    mood="neutral",
                    tension=0.35,
                    energy=0.2,
                    desired_duration=end - start,
                    generation_allowed=False,
                    notes=reason,
                )
            )
        else:
            needs.append(
                SoundNeed(
                    sound_need_id=f"music_{index:02d}",
                    start=start,
                    end=end,
                    scene_ids=scene_ids,
                    chapter=name,
                    type="music",
                    story_reason=reason,
                    importance="high" if music >= 0.6 else "medium",
                    mood="investigative" if music >= 0.55 else "reflective",
                    tension=_t,
                    energy=music,
                    desired_texture="muted pulse textural strings",
                    desired_duration=end - start,
                    reuse_allowed=True,
                    generation_allowed=True,
                )
            )
        if "warehouse" in name or "discovery" in name:
            needs.append(
                SoundNeed(
                    sound_need_id=f"ambience_{index:02d}",
                    start=start,
                    end=min(end, start + 18.0),
                    scene_ids=scene_ids[:4],
                    chapter=name,
                    type="ambience",
                    story_reason="Warehouse room tone under discovery.",
                    importance="medium",
                    mood="industrial quiet",
                    desired_texture="warehouse room tone metal",
                    desired_duration=min(18.0, end - start),
                    notes=(
                        f"veo:{next(iter(veo_candidates.values()))}" if veo_candidates else ""
                    ),
                )
            )
    event_slots = _sparse_events(timeline)
    for index, (start, end, scene_id, kind, reason) in enumerate(event_slots):
        needs.append(
            SoundNeed(
                sound_need_id=f"{kind}_{index:02d}",
                start=start,
                end=end,
                scene_ids=[scene_id],
                chapter="",
                type="event_sfx" if kind == "event" else "transition_sting",
                story_reason=reason,
                importance="low",
                mood="restrained",
                desired_texture="metal" if kind == "event" else "low sting",
                desired_duration=end - start,
                sync_required=kind == "event",
            )
        )
    return needs


def _sparse_events(timeline: RuntimeTimeline) -> list[tuple[float, float, str, str, str]]:
    events: list[tuple[float, float, str, str, str]] = []
    used_kinds = 0
    for timing in timeline.scenes:
        text = timing.narration.casefold()
        if used_kinds >= 10:
            break
        if any(token in text for token in ("fıçı", "fici", "varil", "kapak")) and used_kinds < 4:
            events.append(
                (
                    timing.start + min(1.2, timing.duration * 0.3),
                    timing.start + min(1.8, timing.duration * 0.45),
                    timing.scene_id,
                    "event",
                    "restrained barrel/lid metal contact",
                )
            )
            used_kinds += 1
        if any(token in text for token in ("kamyon", "tır", "tir", "yol")) and used_kinds < 8:
            events.append(
                (
                    timing.start,
                    min(timing.end, timing.start + 2.5),
                    timing.scene_id,
                    "event",
                    "distant truck pass, generic",
                )
            )
            used_kinds += 1
        if any(token in text for token in ("mahkeme", "iddianame", "belge", "rapor")):
            events.append(
                (
                    max(timing.start - 0.15, 0.0),
                    timing.start + 0.9,
                    timing.scene_id,
                    "sting",
                    "restrained document/court transition accent",
                )
            )
            used_kinds += 1
    return events[:12]


def _music_sections(
    needs: list[SoundNeed],
    _chapters: list[dict[str, object]],
    _duration: float,
) -> list[MusicSection]:
    music_needs = [item for item in needs if item.type == "music"]
    if not music_needs:
        return []
    merged: list[SoundNeed] = []
    current = music_needs[0]
    for item in music_needs[1:]:
        compatible = (
            abs(item.tension - current.tension) < 0.2
            and item.mood == current.mood
            and item.start - current.end < 8.0
        )
        if compatible:
            current = current.model_copy(
                update={
                    "end": item.end,
                    "scene_ids": current.scene_ids + item.scene_ids,
                    "desired_duration": item.end - current.start,
                }
            )
        else:
            merged.append(current)
            current = item
    merged.append(current)
    sections: list[MusicSection] = []
    for need in merged:
        sections.append(
            MusicSection(
                music_section_id=need.sound_need_id,
                start=need.start,
                end=need.end,
                chapter_ids=[need.chapter],
                purpose=need.story_reason,
                mood=need.mood,
                tension_start=need.tension,
                tension_peak=min(1.0, need.tension + 0.12),
                tension_end=max(0.1, need.tension - 0.08),
                energy_start=need.energy,
                energy_end=max(0.15, need.energy - 0.1),
                bpm_range="56-76" if need.mood == "reflective" else "64-84",
                density="low" if need.energy < 0.5 else "medium",
                brightness="dark",
                visual_context_scene_ids=need.scene_ids[:6],
                generation_prompt="",
                status="planned",
            )
        )
    return sections


def _merge_music_sections(sections: list[MusicSection], limit: int) -> list[MusicSection]:
    while len(sections) > limit:
        best_i = 0
        best_gap = 1e9
        for index in range(len(sections) - 1):
            gap = sections[index + 1].start - sections[index].end
            mood_penalty = 0 if sections[index].mood == sections[index + 1].mood else 20
            if gap + mood_penalty < best_gap:
                best_gap = gap + mood_penalty
                best_i = index
        left = sections[best_i]
        right = sections[best_i + 1]
        combined = left.model_copy(
            update={
                "end": right.end,
                "chapter_ids": left.chapter_ids + right.chapter_ids,
                "tension_end": right.tension_end,
                "energy_end": right.energy_end,
                "visual_context_scene_ids": (
                    left.visual_context_scene_ids + right.visual_context_scene_ids
                )[:6],
            }
        )
        sections = [*sections[:best_i], combined, *sections[best_i + 2 :]]
    return sections


def render_sound_plan_markdown(plan: SoundPlan) -> str:
    lines = [
        "# Sound plan v1",
        "",
        (
            "| time | chapter | story state | tension | music | ambience | "
            "event SFX | transition | reuse/generate | reason |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for knot in plan.knots:
        music = next(
            (
                "yes"
                for cue in plan.cues
                if cue.type == "music" and cue.start <= knot.time < cue.end
            ),
            "no",
        )
        ambience = next(
            (
                "yes"
                for cue in plan.cues
                if cue.type == "ambience" and cue.start <= knot.time < cue.end
            ),
            "no",
        )
        event = next(
            (
                "yes"
                for cue in plan.cues
                if cue.type == "event_sfx" and abs(cue.start - knot.time) < 8
            ),
            "no",
        )
        sting = next(
            (
                "yes"
                for cue in plan.cues
                if cue.type == "transition_sting" and abs(cue.start - knot.time) < 8
            ),
            "no",
        )
        reuse = "generate" if plan.generation_required_music else "reuse"
        lines.append(
            f"| {knot.time:.1f} | {knot.chapter} | {knot.story_state} | {knot.tension:.2f} | "
            f"{music} | {ambience} | {event} | {sting} | {reuse} | {knot.reason} |"
        )
    lines.append("")
    lines.append(f"Music sections: {len(plan.music_sections)} (not a fixed three-track template)")
    lines.append(f"Silence spans: {len(plan.silence_spans)}")
    return "\n".join(lines) + "\n"
