from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from docprod.audio.models import RuntimeSceneTiming, RuntimeTimeline
from docprod.audio.sound_models import SoundCue, SoundPlan
from docprod.audio.sound_plan import (
    build_sound_plan,
    default_sonic_profile,
    render_sound_plan_markdown,
)
from docprod.drama import DEFAULT_PROJECT_ID, EPISODE_MODE
from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import CHARACTER_REF_PLAN, LOGLINE, build_birko_script
from docprod.drama.titles import render_cinematic_title_card
from docprod.drama.uniqueness import (
    assert_unique_cinematic_visuals,
    collage_violations,
    duplicate_fingerprints,
)
from docprod.models.enums import JobStatus
from docprod.models.job import JobState
from docprod.models.project import Project
from docprod.models.scene import ScenePlan, SourceReference
from docprod.providers.image_config import ImageGenerationConfig
from docprod.research.models import TopicSpec
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths, ensure_project_layout, project_paths


@dataclass
class CustomDramaPlanResult:
    project_id: str
    script_words: int
    runtime_minutes: float
    scene_count: int
    title_cards: list[str]
    title_card_scene_ids: list[str]
    ai_still_count: int
    duplicate_visuals: list[tuple[str, str]]
    collage_violations: list[str]
    planned_paid: dict[str, str]
    review_path: Path


def is_custom_drama(project: Project) -> bool:
    return str(project.metadata.get("episode_mode") or "") == EPISODE_MODE


def _planned_timeline(plan) -> RuntimeTimeline:
    return RuntimeTimeline(
        project_id=plan.project_id,
        audio_duration=plan.total_duration,
        total_duration=plan.total_duration,
        scenes=[
            RuntimeSceneTiming(
                scene_id=scene.id,
                start=scene.start,
                end=scene.end,
                duration=scene.duration,
                planned_duration=scene.duration,
                narration=scene.narration,
                asset_unit_id=str(scene.metadata.get("asset_unit_id") or ""),
            )
            for scene in plan.scenes
        ],
    )


def _review_markdown(result: CustomDramaPlanResult, script, plan, sound) -> str:
    titles = "\n".join(f"- `{sid}`: {title}" for sid, title in zip(
        result.title_card_scene_ids, result.title_cards, strict=True
    ))
    dup = "none" if not result.duplicate_visuals else str(result.duplicate_visuals)
    collage = "none" if not result.collage_violations else ", ".join(result.collage_violations)
    stills = [s for s in plan.scenes if not s.metadata.get("cinematic_title_card")]
    durs = [float(s.duration) for s in stills]
    mean_shot = sum(durs) / len(durs) if durs else 0.0
    max_shot = max(durs) if durs else 0.0
    refs = "\n".join(
        f"- `{item['id']}` ({item['character']}): {item['role']}" for item in CHARACTER_REF_PLAN
    )
    beats = "\n".join(
        f"- {b.beat_id} ({b.purpose}): {b.narration[:80]}…" for b in script.beats
    )
    spend = "\n".join(f"- {k}: {v}" for k, v in result.planned_paid.items())
    return f"""# Custom short drama — {result.project_id}

## Mode
Fictional narrated neighborhood drama. No research, no web sourcing, no factual documentary spine.

## Logline
{LOGLINE}

## Script structure
1. Cold open — sır tutulmaz / iki isim (before first card)
2. İki İsim — Kemal, Müge, first “Kemal’e yaz.” / “O öder.”
3. Birko İçeride — merdiven, parfüm, boya, şeker, dedikodu, küpe
4. Hesap Kapanır — kahkaha, “hesabını da götür,” bakkal payoff
5. End — pocket, then “Mahalle aşkı konuşur. Ama hesabı herkes kendi öder.”

Word count: {result.script_words}
Estimated narration: {result.runtime_minutes:.2f} min

## Chapter titles
{titles}

## Beats
{beats}

## Visual pacing
- narrative stills: {len(stills)}
- mean narrative shot: {mean_shot:.2f}s
- max narrative shot: {max_shot:.2f}s
- title cards: {len(result.title_cards)} × 1.1s
- first scene is cold open, not a title card

## Character references (proposed, not generated)
{refs}

Three chest-up identity stills as generation inputs only. They must not appear as
timeline visuals. Timeline images may use them as references later.

## Scene plan
- scenes: {result.scene_count}
- cinematic title cards: {len(result.title_cards)}
- unique AI stills planned: {result.ai_still_count}
- duplicate visuals: {dup}
- collage/explainer violations: {collage}

Title-card: previous scene → dip-to-black → 0.35s local whoosh → 1.1s dark title
→ next scene immediately. Ledger-close SFX is planned on the bakkal payoff.
Pocket rustle is planned, not slapstick.

## Sound plan (planned timing)
- music sections: {len(sound.music_sections)}
- ambience cues: {sum(1 for c in sound.cues if c.type == 'ambience')}
- event SFX: {sum(1 for c in sound.cues if c.type == 'event_sfx')}
- transition stings: {sum(1 for c in sound.cues if c.type == 'transition_sting')}
- silence spans: {len(sound.silence_spans)}

## Planned paid spend (NOT executed)
{spend}

No paid APIs were called while producing this plan.
"""


_EVENT_SFX = {
    "ledger_close": ("Ledger close — bakkal payoff", 0.45, -8.0),
    "pocket": ("Quiet pocket rustle — Birko pays himself", 0.5, -14.0),
    "cola_set": ("Bottle on wood", 0.22, -16.0),
    "window_open": ("Window sash", 0.3, -18.0),
}
_AMBIENCE = {
    "bakkal_ambience": "Bakkal room tone",
    "apartment_tone": "Apartment room tone",
    "stairwell_tone": "Stairwell room tone",
    "elevator_tone": "Elevator hum",
}


def _attach_drama_audio(sound: SoundPlan, plan: ScenePlan) -> SoundPlan:
    extra: list[SoundCue] = []
    for scene in plan.scenes:
        if scene.metadata.get("cinematic_title_card"):
            extra.append(
                SoundCue(
                    cue_id=f"cue_title_sting_{scene.id}",
                    sound_need_id=f"need_title_sting_{scene.id}",
                    type="transition_sting",
                    start=scene.start,
                    end=round(min(scene.end, scene.start + 0.35), 4),
                    scene_ids=[scene.id],
                    source_type="TRANSITION_STING",
                    generated_or_reused="local_generic",
                    sync_required=True,
                    gain_db=-10.0,
                    fade_in=0.01,
                    fade_out=0.08,
                    duck_under_voice=False,
                    story_reason=f"Hard cut into title: {scene.metadata.get('chapter_title')}",
                    license_or_generation_metadata="local whoosh/impact; not generated",
                    status="planned",
                )
            )
            continue
        kind = str(scene.metadata.get("planned_sfx") or "")
        if kind in _AMBIENCE:
            extra.append(
                SoundCue(
                    cue_id=f"cue_amb_{scene.id}",
                    sound_need_id=f"need_amb_{scene.id}",
                    type="ambience",
                    start=scene.start,
                    end=scene.end,
                    scene_ids=[scene.id],
                    source_type="AMBIENCE",
                    generated_or_reused="local_generic",
                    gain_db=-28.0,
                    fade_in=0.2,
                    fade_out=0.3,
                    duck_under_voice=True,
                    story_reason=_AMBIENCE[kind],
                    license_or_generation_metadata="local room tone; not generated",
                    status="planned",
                )
            )
        if kind in _EVENT_SFX:
            reason, dur, gain = _EVENT_SFX[kind]
            start = round(scene.start + min(0.35, scene.duration * 0.25), 4)
            extra.append(
                SoundCue(
                    cue_id=f"cue_sfx_{scene.id}",
                    sound_need_id=f"need_sfx_{scene.id}",
                    type="event_sfx",
                    start=start,
                    end=round(min(scene.end, start + dur), 4),
                    scene_ids=[scene.id],
                    source_type="EVENT_SFX",
                    generated_or_reused="local_generic",
                    sync_required=True,
                    gain_db=gain,
                    fade_in=0.01,
                    fade_out=0.08,
                    duck_under_voice=False,
                    story_reason=reason,
                    license_or_generation_metadata="local event; not generated",
                    status="planned",
                )
            )
    return sound.model_copy(
        update={
            "cues": list(sound.cues) + extra,
            "paid_api_calls": {"lyria_3_5": 0, "lyria_realtime": 0},
            "notes": [
                *sound.notes,
                "custom_short_drama: title stings and event SFX are local; no paid audio",
            ],
        }
    )


def plan_custom_drama(
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    paths: ProjectPaths | None = None,
) -> CustomDramaPlanResult:
    dest = paths or project_paths(project_id)
    ensure_project_layout(dest)
    now = datetime.now(UTC)
    project = Project(
        id=project_id,
        title="Hain Birko ve Baby Kemal",
        language="tr",
        target_duration_seconds=150.0,
        created_at=now,
        updated_at=now,
        metadata={
            "episode_mode": EPISODE_MODE,
            "skip_research": True,
            "fictional": True,
        },
    )
    if dest.project_json.is_file():
        loaded = load_model(dest.project_json, Project)
        project = loaded.model_copy(
            update={"updated_at": now, "metadata": {**loaded.metadata, **project.metadata}}
        )
    save_model(dest.project_json, project)
    if not dest.job_json.is_file():
        save_model(
            dest.job_json,
            JobState(
                project_id=project_id,
                status=JobStatus.pending,
                created_at=now,
                updated_at=now,
            ),
        )
    save_model(
        dest.topic_json(),
        TopicSpec(
            project_id=project_id,
            topic="Hain Birko, Baby Kemal ve mahalle ihaneti (kurgusal kısa drama)",
            language="tr",
            target_runtime_minutes=2.5,
            target_audience="adult neighborhood-drama viewers",
            content_type="custom_short_drama",
            research_notes_optional="Fictional. Do not web-research. Do not treat as documentary.",
        ),
    )
    script = build_birko_script(project_id=project_id)
    save_model(dest.story_script_json(), script)
    plan = compile_drama_scene_plan(script)
    title_dir = dest.visuals_dir / "chapter_titles"
    title_dir.mkdir(parents=True, exist_ok=True)
    for stale in title_dir.glob("*.jpg"):
        stale.unlink()
    title_names: list[str] = []
    title_ids: list[str] = []
    scenes = []
    for scene in plan.scenes:
        if scene.metadata.get("cinematic_title_card"):
            title = str(scene.metadata["chapter_title"])
            card = title_dir / f"{scene.id}.jpg"
            render_cinematic_title_card(title, card)
            rel = card.relative_to(dest.root).as_posix()
            scene = scene.model_copy(
                update={
                    "sources": [
                        SourceReference(local_path=rel, title=title, license="internal-title-card")
                    ]
                }
            )
            title_names.append(title)
            title_ids.append(scene.id)
        scenes.append(scene)
    plan = plan.model_copy(update={"scenes": scenes})
    assert_unique_cinematic_visuals(plan)
    save_model(dest.scene_plan_json, plan)
    timeline = _planned_timeline(plan)
    save_model(dest.runtime_timeline_json(), timeline)
    sound = _attach_drama_audio(
        build_sound_plan(
            project_id=project_id,
            timeline=timeline,
            scenes=plan,
            script=script,
            profile=default_sonic_profile(),
        ),
        plan,
    )
    save_model(dest.sound_plan_json(), sound)
    dest.sound_plan_review_md().write_text(render_sound_plan_markdown(sound), encoding="utf-8")
    stills = [s for s in plan.scenes if not s.metadata.get("cinematic_title_card")]
    image_cfg = ImageGenerationConfig.from_settings()
    hist = 0.06698
    result = CustomDramaPlanResult(
        project_id=project_id,
        script_words=script.word_count,
        runtime_minutes=script.estimated_runtime_minutes,
        scene_count=len(plan.scenes),
        title_cards=title_names,
        title_card_scene_ids=title_ids,
        ai_still_count=len(stills),
        duplicate_visuals=duplicate_fingerprints(plan),
        collage_violations=collage_violations(plan),
        planned_paid={
            "research_web": "$0 (skipped)",
            "writer_llm": "$0 (local authored script)",
            "scene_planner_llm": "$0 (local drama compiler)",
            "character_refs_proposed": (
                f"{len(CHARACTER_REF_PLAN)} identity stills as generation inputs "
                f"only, not timeline; ESTIMATED "
                f"{len(CHARACTER_REF_PLAN)}×${hist:.5f}="
                f"${len(CHARACTER_REF_PLAN)*hist:.4f}; not executed"
            ),
            "ai_stills": (
                f"KNOWN model={image_cfg.model} quality={image_cfg.quality} "
                f"size={image_cfg.size}; KNOWN token rates $5/$8/$30 per 1M "
                "(text in / image in / image out); ESTIMATED "
                f"{len(stills)}×${hist:.5f}=${len(stills)*hist:.4f} from "
                "existing_image_cost_usd historical sample; per-image list "
                "price UNRESOLVED (usage-based); not executed"
            ),
            "image_generations_proposed": (
                f"{len(stills)} timeline + {len(CHARACTER_REF_PLAN)} refs = "
                f"{len(stills)+len(CHARACTER_REF_PLAN)}; ESTIMATED "
                f"${(len(stills)+len(CHARACTER_REF_PLAN))*hist:.4f} historical"
            ),
            "title_cards": f"{len(title_names)} local cinematic cards — $0",
            "tts": (
                "KNOWN rates $0.60/1M text in, $12/1M audio out "
                f"(gpt-4o-mini-tts); episode total UNRESOLVED without usage; "
                f"~{script.estimated_runtime_minutes:.2f} min planned; not executed"
            ),
            "whisper": (
                "KNOWN $0.006/min; ESTIMATED "
                f"${script.estimated_runtime_minutes * 0.006:.5f} at script "
                "runtime (alignment uses actual TTS duration); not executed"
            ),
            "veo": "0 (prototype: stills + motion on stills only)",
            "lyria": "0 this plan; optional later 1–2 beds at $0.08 each",
            "pexels": "0 (AI stills preferred over stock reuse)",
            "total_this_step": "$0 (plan + local title cards only)",
        },
        review_path=dest.review_dir / "custom_drama_plan.md",
    )
    result.review_path.write_text(
        _review_markdown(result, script, plan, sound), encoding="utf-8"
    )
    return result
