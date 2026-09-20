from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from docprod.audio.cues import chunk_alignment_cues
from docprod.audio.mix import measure_loudnorm
from docprod.audio.models import DRAMA_VOICE_INSTRUCTIONS, AlignmentReport, RuntimeTimeline
from docprod.audio.sound_library import SoundLibrary
from docprod.audio.sound_models import MusicSection, SonicProfile, SoundAsset, SoundCue, SoundPlan
from docprod.audio.sound_plan import build_sound_plan, render_sound_plan_markdown
from docprod.audio.soundtrack_mix import mix_soundtrack, synthesize_generic
from docprod.audio.timeline import apply_runtime_timeline, build_runtime_timeline
from docprod.audio.tts_preflight import inspect_tts_input
from docprod.config import get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.drama.timeline import (
    filter_cues_over_titles,
    insert_title_windows,
    is_title_card,
    pad_wav_with_silences,
    shift_alignment,
    spoken_scene_plan,
    title_windows,
)
from docprod.drama.uniqueness import assert_unique_cinematic_visuals, duplicate_fingerprints
from docprod.models.project import Project
from docprod.models.scene import ScenePlan
from docprod.pipeline.generate_drama_visuals import _cost_from_usage
from docprod.pipeline.generate_narration import generate_narration, prepare_narration
from docprod.pipeline.plan_custom_drama import _attach_drama_audio
from docprod.pipeline.render_review_episode import _tts_cost_usd
from docprod.providers.google_lyria import (
    GoogleLyriaProvider,
    normalize_music_to_wav,
    select_lyria_images,
    sniff_audio_format,
)
from docprod.providers.music_base import MusicGenerateRequest
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.pricing import LYRIA_IMAGE_LIMIT, MUSIC_DUCK_DB, lyria_cost_usd
from docprod.providers.request_budget import ModelRequestBudget
from docprod.render.contact_sheet import build_contact_sheet
from docprod.render.ffmpeg import FFmpegError, discover_font, probe_media, run_ffmpeg
from docprod.render.models import FinalRenderProfile
from docprod.render.mux import mux_audio_copy_video
from docprod.render.renderer import render_preview
from docprod.render.still import resolve_scene_visual
from docprod.render.subtitles import build_ass_from_cues, build_srt_from_cues
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_text, save_json, save_model
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import WORDS_PER_MINUTE, NarrationScript

ProgressFn = Callable[[str], None]
LYRIA_DRAMA_MAX = 2
FINAL_NAME = "birko_kemal_drama_v1.mp4"
LEDGER_TOKEN = "ödemiyor"


@dataclass
class DramaProductionReport:
    narration_model: str = ""
    narration_duration: float = 0.0
    tts_spend_usd: float | None = None
    whisper_matched: int = 0
    whisper_interpolated: int = 0
    whisper_unmatched: int = 0
    alignment_confidence: float = 0.0
    whisper_spend_usd: float = 0.0
    scene_count: int = 0
    unique_narrative_visuals: int = 0
    duplicate_visuals: int = 0
    title_card_count: int = 0
    title_timings: list[str] = field(default_factory=list)
    lyria_generation_count: int = 0
    lyria_spend_usd: float = 0.0
    music_audible: bool = False
    sfx_count: int = 0
    chapter_sting_count: int = 0
    ledger_close_present: bool = False
    subtitle_cue_count: int = 0
    lufs: str = ""
    true_peak: str = ""
    final_duration: float = 0.0
    visual_rerenders: int = 0
    new_paid_spend_usd: float = 0.0
    previous_image_cost_usd: float | None = None
    total_episode_cost_usd: float | None = None
    music_decision: str = ""
    notes: list[str] = field(default_factory=list)
    production_path: str = ""
    qc_path: str = ""


def produce_custom_drama(
    paths: ProjectPaths,
    *,
    project: Project,
    confirm_paid: bool,
    progress: ProgressFn | None = None,
) -> DramaProductionReport:
    def log(message: str) -> None:
        if progress:
            progress(message)

    report = DramaProductionReport()
    plan = _load_plan(paths)
    assert_unique_cinematic_visuals(plan)
    spoken = spoken_scene_plan(plan)
    settings = get_settings()
    prepared = prepare_narration(
        paths, spoken, settings=settings, voice_instructions=DRAMA_VOICE_INSTRUCTIONS
    )
    preflight = inspect_tts_input(prepared.script.text)
    est_sec = prepared.word_count / WORDS_PER_MINUTE * 60.0
    log(f"tts_model={prepared.model}")
    log(f"tts_voice={prepared.voice}")
    log(f"character_count={prepared.character_count}")
    log(f"estimated_tokens={preflight.estimated_tokens}")
    log(f"estimated_duration_s={est_sec:.2f}")
    log("known_tts_pricing=$0.60/1M text in + $12/1M audio out")
    est_tts = round(preflight.estimated_tokens * 0.60 / 1_000_000, 6)
    log(f"estimated_tts_input_cost_usd={est_tts} (audio-out unresolved until usage)")
    log("whisper_pricing=$0.006/min")
    log(f"estimated_whisper_usd={round(est_sec / 60.0 * 0.006, 6)}")
    require_paid_call_allowed("openai", confirm_paid=confirm_paid, settings=settings)
    narration = generate_narration(
        paths,
        project=project,
        plan=spoken,
        confirm_paid=confirm_paid,
        settings=settings,
        voice_instructions=DRAMA_VOICE_INSTRUCTIONS,
    )
    speech_wav = paths.narration_master_wav()
    speech_probe = probe_media(speech_wav)
    spoken_timeline = build_runtime_timeline(
        spoken, narration.alignment, audio_duration=speech_probe.duration
    )
    runtime_wav = paths.narration_dir / "master.runtime.wav"
    padded_timeline, inserts = insert_title_windows(
        plan, spoken_timeline, audio_duration=speech_probe.duration
    )
    pad_wav_with_silences(speech_wav, runtime_wav, inserts)
    alignment = shift_alignment(narration.alignment, inserts)
    save_model(paths.narration_alignment_json(), alignment)
    save_model(paths.runtime_timeline_json(), padded_timeline)
    plan = apply_runtime_timeline(plan, padded_timeline)
    save_model(paths.scene_plan_json, plan)

    report.narration_model = narration.meta.model
    report.narration_duration = speech_probe.duration
    tts_usd, tts_basis = _tts_cost_usd(
        narration.meta.usage if isinstance(narration.meta.usage, dict) else None
    )
    report.tts_spend_usd = tts_usd
    report.whisper_matched = alignment.matched_word_count
    report.whisper_interpolated = alignment.interpolated_word_count
    report.whisper_unmatched = alignment.unmatched_word_count
    report.alignment_confidence = alignment.match_fraction
    report.whisper_spend_usd = round(speech_probe.duration / 60.0 * 0.006, 6)
    log(f"narration_duration={speech_probe.duration:.3f}s")
    log(
        f"alignment matched={alignment.matched_word_count} "
        f"interpolated={alignment.interpolated_word_count} "
        f"unmatched={alignment.unmatched_word_count} "
        f"confidence={alignment.match_fraction:.3f}"
    )
    log(f"tts_spend={tts_usd} basis={tts_basis}")
    log(f"whisper_spend_usd={report.whisper_spend_usd}")

    cues = filter_cues_over_titles(
        chunk_alignment_cues(alignment), title_windows(padded_timeline, plan)
    )
    font = discover_font()
    profile = FinalRenderProfile(motion_oversample_factor=2, burn_subtitles=True, preset="medium")
    atomic_write_text(paths.captions_srt, build_srt_from_cues(cues))
    atomic_write_text(
        paths.captions_ass,
        build_ass_from_cues(
            cues,
            play_res_x=profile.width,
            play_res_y=profile.height,
            font_name=font.stem,
        ),
    )
    report.subtitle_cue_count = len(cues)

    visual = render_preview(
        paths,
        project=project,
        plan=plan,
        profile=profile,
        use_cache=True,
        allow_placeholders=False,
        alignment=alignment,
        write_caption_files=False,
        captions_srt=paths.captions_srt,
        captions_ass=paths.captions_ass,
        progress=log,
    )
    report.visual_rerenders = visual.rendered_segments
    visual_master = paths.production_dir() / "visual_master_drama_v1.mp4"
    visual_master.parent.mkdir(parents=True, exist_ok=True)
    _strip_audio_copy_or_encode(paths.preview_mp4, visual_master)

    music_decision = (
        "ONE Lyria generation first. Lyria Interactions clips are typically ~30s; "
        "looping a single bed across ~1:45 would be noticeable. A second generation "
        "is used only if the first clip cannot cover the episode without looping. "
        f"Hard cap={LYRIA_DRAMA_MAX}."
    )
    report.music_decision = music_decision
    log(f"lyria_decision={music_decision}")

    sound_plan = _build_drama_sound(
        paths, plan, padded_timeline, alignment, log=log
    )
    require_paid_call_allowed("google", confirm_paid=confirm_paid, settings=settings)
    require_gemini_api_key(settings)
    lyria_used, lyria_cached = _materialize_drama_music(
        paths, sound_plan, plan, confirm_paid=confirm_paid, log=log
    )
    _materialize_local_sfx(paths, sound_plan)
    save_model(paths.sound_plan_json(), sound_plan)
    paths.sound_plan_review_md().write_text(
        render_sound_plan_markdown(sound_plan), encoding="utf-8"
    )
    report.lyria_generation_count = lyria_used
    report.lyria_spend_usd = lyria_cost_usd(lyria_used)
    log(f"lyria_generations_billed={lyria_used} cached={lyria_cached}")
    log(f"lyria_spend_usd={report.lyria_spend_usd}")

    mix_wav = paths.production_mix_wav()
    loudness = mix_soundtrack(
        narration=runtime_wav,
        plan=sound_plan,
        assets=_cue_assets(paths, sound_plan),
        dest=mix_wav,
        timeline=padded_timeline,
        loop_music=False,
    )
    report.lufs = str(loudness.get("input_i") or loudness.get("output_i") or "")
    report.true_peak = str(loudness.get("input_tp") or loudness.get("output_tp") or "")
    mix_stats = measure_loudnorm(mix_wav)
    report.lufs = str(mix_stats.get("input_i") or report.lufs)
    report.true_peak = str(mix_stats.get("input_tp") or report.true_peak)

    music_ok, music_notes = _qc_music_audible(mix_wav, runtime_wav, padded_timeline)
    report.music_audible = music_ok
    report.notes.extend(music_notes)
    if not music_ok:
        raise RuntimeError("Mix failed music-audible QC (narration-only regression).")

    dest = paths.production_dir() / FINAL_NAME
    mux_audio_copy_video(visual_master, mix_wav, dest)
    probe = probe_media(dest)
    report.final_duration = probe.duration
    report.production_path = str(dest)

    qc = _visual_qc(paths, plan, padded_timeline, dest)
    report.scene_count = len(plan.scenes)
    report.unique_narrative_visuals = qc["unique_narrative"]
    report.duplicate_visuals = qc["duplicate_timeline"]
    report.title_card_count = qc["title_cards"]
    report.title_timings = qc["title_timings"]
    report.sfx_count = sum(1 for cue in sound_plan.cues if cue.type == "event_sfx")
    report.chapter_sting_count = sum(
        1 for cue in sound_plan.cues if cue.type == "transition_sting"
    )
    report.ledger_close_present = any(
        "ledger" in (cue.story_reason or "").casefold()
        or "ledger" in cue.cue_id
        for cue in sound_plan.cues
        if cue.type == "event_sfx"
    )
    report.notes.extend(qc["notes"])
    if report.unique_narrative_visuals != 21 or report.duplicate_visuals != 0:
        raise RuntimeError(
            f"Uniqueness QC failed: unique={report.unique_narrative_visuals} "
            f"dupes={report.duplicate_visuals}"
        )
    if report.title_card_count != 3:
        raise RuntimeError(f"Expected 3 title cards, got {report.title_card_count}")
    if padded_timeline.scenes[0].narration.strip() == "":
        raise RuntimeError("First timeline beat must be the cold open, not a title card")

    prev_image = _previous_image_cost(paths)
    report.previous_image_cost_usd = prev_image
    new_spend = (tts_usd or 0.0) + report.whisper_spend_usd + report.lyria_spend_usd
    report.new_paid_spend_usd = round(new_spend, 6)
    if prev_image is not None:
        report.total_episode_cost_usd = round(prev_image + new_spend, 6)
    report.qc_path = str(_write_qc_markdown(paths, report, plan, sound_plan, padded_timeline))
    _final_contact_sheet(paths, plan)
    save_json(
        paths.review_dir / "drama_production_costs.json",
        {
            "previous_image_cost_usd": prev_image,
            "new_tts_cost_usd": tts_usd,
            "new_whisper_cost_usd": report.whisper_spend_usd,
            "new_lyria_cost_usd": report.lyria_spend_usd,
            "total_new_spend_usd": report.new_paid_spend_usd,
            "total_episode_known_usd": report.total_episode_cost_usd,
            "lyria_cached": lyria_cached,
            "tts_request_count": narration.tts_request_count,
            "whisper_request_count": narration.whisper_request_count,
        },
    )
    return report


def _load_plan(paths: ProjectPaths) -> ScenePlan:
    if not paths.scene_plan_json.is_file():
        raise FileNotFoundError(f"Missing scene plan: {paths.scene_plan_json}")
    from docprod.storage.json_store import load_model

    return load_model(paths.scene_plan_json, ScenePlan)


def _strip_audio_copy_or_encode(source: Path, dest: Path) -> None:
    tmp = dest.with_suffix(".tmp.mp4")
    try:
        run_ffmpeg(
            ["-i", str(source), "-map", "0:v:0", "-an", "-c:v", "copy", str(tmp)],
            timeout=180,
        )
        tmp.replace(dest)
    except FFmpegError:
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "medium",
                "-crf",
                "20",
                str(tmp),
            ],
            timeout=300,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _drama_profile() -> SonicProfile:
    return SonicProfile(
        name="neighborhood_drama_v1",
        genre="short drama underscore",
        tone="curious, suspicious, restrained ironic",
        resolution_palette="quiet neighborhood irony",
    )


def _build_drama_sound(
    paths: ProjectPaths,
    plan: ScenePlan,
    timeline: RuntimeTimeline,
    alignment: AlignmentReport,
    *,
    log: ProgressFn,
) -> SoundPlan:
    script = None
    if paths.story_script_json().is_file():
        from docprod.storage.json_store import load_model

        script = load_model(paths.story_script_json(), NarrationScript)
    sound = build_sound_plan(
        project_id=plan.project_id,
        timeline=timeline,
        scenes=plan,
        script=script,
        profile=_drama_profile(),
    )
    sound = _attach_drama_audio(sound, plan)
    sound = _force_two_or_one_music(sound, timeline, plan)
    sound = _retarget_ledger(sound, alignment, plan)
    log(
        f"sound_cues music={sum(1 for c in sound.cues if c.type == 'music')} "
        f"stings={sum(1 for c in sound.cues if c.type == 'transition_sting')} "
        f"sfx={sum(1 for c in sound.cues if c.type == 'event_sfx')}"
    )
    return sound


def _force_two_or_one_music(
    sound: SoundPlan, timeline: RuntimeTimeline, plan: ScenePlan
) -> SoundPlan:
    duration = timeline.total_duration
    titles = [item for item in timeline.scenes if is_title_card(_scene(plan, item.scene_id))]
    third_start = titles[2].start if len(titles) >= 3 else duration * 0.72
    if len(titles) >= 2:
        open_end = max(18.0, min(titles[1].start + 2.0, third_start - 6.0))
    else:
        open_end = 32.0
    section_a = MusicSection(
        music_section_id="music_open",
        start=0.0,
        end=round(open_end, 4),
        chapter_ids=["ch_names"],
        purpose="Curious opening into suspicious neighborhood escalation",
        mood="curious tension",
        tension_start=0.35,
        tension_peak=0.55,
        tension_end=0.5,
        energy_start=0.28,
        energy_end=0.42,
        bpm_range="58-76",
        density="low",
        brightness="dark",
        tonal_direction="neighborhood drama underscore",
        instrumentation="dry piano, muted strings, low pulse, no vocals",
        generation_prompt=_lyria_prompt_open(),
        generation_required=True,
        status="generate",
        visual_context_scene_ids=[item.scene_id for item in timeline.scenes[:4]],
    )
    section_b = MusicSection(
        music_section_id="music_close",
        start=round(max(0.0, third_start - 1.0), 4),
        end=round(duration, 4),
        chapter_ids=["ch_ledger"],
        purpose="Confrontation tension then restrained ironic bakkal resolution",
        mood="tense then ironic resolve",
        tension_start=0.62,
        tension_peak=0.7,
        tension_end=0.28,
        energy_start=0.45,
        energy_end=0.22,
        bpm_range="60-80",
        density="medium",
        brightness="dark",
        generation_prompt=_lyria_prompt_close(),
        generation_required=True,
        status="generate",
        visual_context_scene_ids=[item.scene_id for item in timeline.scenes[-6:]],
    )
    music_cues = [cue for cue in sound.cues if cue.type != "music"]
    music_cues.extend(
        [
            SoundCue(
                cue_id="cue_music_open",
                sound_need_id="music_open",
                type="music",
                start=section_a.start,
                end=section_a.end,
                scene_ids=section_a.visual_context_scene_ids,
                source_type="MUSIC_BED",
                generated_or_reused="generate",
                gain_db=MUSIC_DUCK_DB,
                fade_in=1.4,
                fade_out=2.2,
                duck_under_voice=True,
                story_reason=section_a.purpose,
                status="planned",
            ),
            SoundCue(
                cue_id="cue_music_close",
                sound_need_id="music_close",
                type="music",
                start=section_b.start,
                end=section_b.end,
                scene_ids=section_b.visual_context_scene_ids,
                source_type="MUSIC_BED",
                generated_or_reused="generate",
                gain_db=MUSIC_DUCK_DB,
                fade_in=1.8,
                fade_out=2.8,
                duck_under_voice=True,
                story_reason=section_b.purpose,
                status="planned",
            ),
        ]
    )
    return sound.model_copy(
        update={
            "music_sections": [section_a, section_b],
            "cues": music_cues,
            "generation_required_music": 2,
            "paid_api_calls": {"lyria_3_5": 2, "lyria_realtime": 0},
            "silence_spans": [],
            "notes": [
                *sound.notes,
                "Drama: two non-looping beds with a quieter middle if needed.",
            ],
        }
    )


def _lyria_prompt_open() -> str:
    return (
        "Instrumental neighborhood short-drama score, no vocals.\n"
        "INSTRUMENTAL ONLY. NO LYRICS. NO VOCALS. NO SPOKEN WORDS.\n"
        "Curious opening, then suspicious escalation under spoken Turkish narration.\n"
        "Dry piano, muted strings, restrained low pulse. Sparse, not a trailer.\n"
        "Avoid: lyrics, vocals, spoken words, giant trailer climaxes, comedy stings."
    )


def _lyria_prompt_close() -> str:
    return (
        "Instrumental neighborhood short-drama score, no vocals.\n"
        "INSTRUMENTAL ONLY. NO LYRICS. NO VOCALS. NO SPOKEN WORDS.\n"
        "Confrontation tension bed that simplifies into a restrained ironic resolution.\n"
        "Leave room for speech. Small resolution tail. No comedy rimshot.\n"
        "Avoid: lyrics, vocals, spoken words, trailer booms, meme sounds."
    )


def _scene(plan: ScenePlan, scene_id: str):
    for scene in plan.scenes:
        if scene.id == scene_id:
            return scene
    raise KeyError(scene_id)


def _retarget_ledger(
    sound: SoundPlan, alignment: AlignmentReport, plan: ScenePlan
) -> SoundPlan:
    hit = None
    for token in alignment.tokens:
        if token.start is None:
            continue
        if LEDGER_TOKEN in token.text.casefold():
            hit = float(token.start)
            break
    if hit is None:
        return sound
    cues = []
    for cue in sound.cues:
        reason = (cue.story_reason or "").casefold()
        if cue.type == "event_sfx" and "ledger" in reason:
            cues.append(
                cue.model_copy(
                    update={"start": round(hit, 4), "end": round(hit + 0.45, 4)}
                )
            )
            continue
        if cue.type == "event_sfx" and "pocket" in reason:
            cues.append(
                cue.model_copy(
                    update={
                        "start": round(hit + 0.7, 4),
                        "end": round(hit + 1.2, 4),
                    }
                )
            )
            continue
        cues.append(cue)
    _ = plan
    return sound.model_copy(update={"cues": cues})


def _materialize_drama_music(
    paths: ProjectPaths,
    sound_plan: SoundPlan,
    plan: ScenePlan,
    *,
    confirm_paid: bool,
    log: ProgressFn,
) -> tuple[int, int]:
    cache = PaidArtifactCache()
    lyria = GoogleLyriaProvider(settings=get_settings(), cache=cache)
    budget = ModelRequestBudget(LYRIA_DRAMA_MAX)
    billed = 0
    cached = 0
    stills = [
        resolve_scene_visual(paths, scene)
        for scene in plan.scenes
        if not is_title_card(scene)
    ]
    frames = select_lyria_images(
        [item.path for item in stills if item is not None][:LYRIA_IMAGE_LIMIT]
    )
    keep: list[MusicSection] = []
    for index, section in enumerate(sound_plan.music_sections):
        if index == 1 and billed == 0 and cached >= 1:
            first = keep[0] if keep else None
            if first is not None:
                wav = paths.soundtrack_dir() / f"{first.music_section_id}.wav"
                if wav.is_file() and probe_media(wav).duration >= sound_plan.duration - 8:
                    log("lyria_second_skipped=first clip covers episode without looping")
                    sound_plan.cues = [
                        cue
                        for cue in sound_plan.cues
                        if cue.sound_need_id != section.music_section_id
                    ]
                    break
        dest = paths.soundtrack_dir() / f"{section.music_section_id}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file():
            cached += 1
            _bind_music_cue(sound_plan, section, dest)
            keep.append(section)
            continue
        result = lyria.generate_music(
            MusicGenerateRequest(
                prompt=section.generation_prompt,
                duration_hint_seconds=32.0,
                image_paths=frames[:3],
            ),
            confirm_paid=confirm_paid,
            use_cache=True,
        )
        cache_hit = (result.metadata or {}).get("cache_hit") == "true"
        if cache_hit:
            cached += 1
        else:
            budget.reserve("lyria", 1)
            billed += 1
        suffix = (result.metadata or {}).get("original_suffix") or sniff_audio_format(
            result.audio_bytes, result.mime
        )[1]
        original = paths.music_original_dir() / f"{section.music_section_id}{suffix}"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(result.audio_bytes)
        normalize_music_to_wav(original, dest)
        clip = probe_media(dest).duration
        section.end = round(min(section.start + clip, sound_plan.duration), 4)
        _bind_music_cue(sound_plan, section, dest)
        keep.append(section)
        log(f"lyria_{section.music_section_id}_duration={clip:.2f}s billed={not cache_hit}")
    sound_plan.music_sections = keep
    sound_plan.generation_required_music = billed
    sound_plan.paid_api_calls = {"lyria_3_5": billed, "lyria_realtime": 0}
    return billed, cached


def _bind_music_cue(sound_plan: SoundPlan, section: MusicSection, dest: Path) -> None:
    clip = probe_media(dest).duration
    end = round(min(section.start + clip, sound_plan.duration), 4)
    section.end = end
    section.status = "ready"
    for cue in sound_plan.cues:
        if cue.sound_need_id == section.music_section_id:
            cue.asset_id = section.music_section_id
            cue.start = section.start
            cue.end = end
            cue.status = "ready"
            cue.generated_or_reused = "generated"
            cue.gain_db = MUSIC_DUCK_DB


def _materialize_local_sfx(paths: ProjectPaths, sound_plan: SoundPlan) -> None:
    library = SoundLibrary(paths.episode_sound_library_json())
    dest_dir = paths.soundtrack_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    for cue in sound_plan.cues:
        if cue.type in {"music", "silence"}:
            continue
        kind = _sfx_kind(cue)
        dest = dest_dir / f"{cue.cue_id}.wav"
        synthesize_generic(kind, dest, duration=max(0.2, cue.end - cue.start))
        cue.asset_id = cue.cue_id
        cue.status = "ready"
        cue.generated_or_reused = "generated_local"
        if cue.type == "transition_sting":
            category = "TRANSITION_STING"
        elif cue.type == "event_sfx":
            category = "EVENT_SFX"
        else:
            category = "AMBIENCE"
        asset = SoundAsset(
            asset_id=cue.cue_id,
            category=category,
            source_type="local_generic",
            prompt=cue.story_reason,
            duration=cue.end - cue.start,
            local_path=str(dest),
            sha256=file_sha256(dest),
            license_note="local procedural; not archival",
        )
        library.add(asset)
    library.save()


def _sfx_kind(cue: SoundCue) -> str:
    blob = f"{cue.cue_id} {cue.story_reason}".casefold()
    if cue.type == "transition_sting":
        return "chapter_sting"
    if "ledger" in blob:
        return "ledger"
    if "pocket" in blob:
        return "pocket"
    if "cola" in blob or "bottle" in blob:
        return "cola"
    if "window" in blob:
        return "window"
    if "elevator" in blob:
        return "elevator"
    if "stair" in blob:
        return "stairwell"
    if "bakkal" in blob:
        return "bakkal"
    if cue.type == "ambience":
        return "apartment"
    return "metal"


def _cue_assets(paths: ProjectPaths, sound_plan: SoundPlan) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    for cue in sound_plan.cues:
        names = [cue.asset_id, cue.sound_need_id, cue.cue_id]
        for name in names:
            if not name:
                continue
            candidate = paths.soundtrack_dir() / f"{name}.wav"
            if candidate.is_file():
                assets[cue.asset_id or name] = candidate
                assets[cue.sound_need_id] = candidate
                assets[cue.cue_id] = candidate
                break
    return assets


def _window_db(path: Path, start: float, duration: float = 0.7) -> float | None:
    from docprod.render.ffmpeg import ffmpeg_path

    completed = subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-ss",
            f"{max(0.0, start):.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    match = re.search(r"mean_volume:\s*([-\d.]+)", completed.stderr or "")
    if not match:
        return None
    return float(match.group(1))


def _qc_music_audible(
    mix: Path, narration: Path, timeline: RuntimeTimeline
) -> tuple[bool, list[str]]:
    duration = timeline.total_duration
    bakkal = max(0.0, duration - 8.0)
    points = [15.0, 35.0, 60.0, 80.0, bakkal]
    notes = []
    audible = 0
    for point in points:
        if point >= duration:
            continue
        mix_db = _window_db(mix, point)
        nar_db = _window_db(narration, point)
        notes.append(f"qc t={point:.1f} mix_db={mix_db} narration_db={nar_db}")
        if mix_db is not None and mix_db > -45:
            audible += 1
        if mix_db is not None and nar_db is not None and mix_db > nar_db + 0.4:
            audible += 1
    ok = audible >= 3
    notes.append(f"music_audible_hits={audible} pass={ok}")
    return ok, notes


def _visual_qc(
    paths: ProjectPaths, plan: ScenePlan, timeline: RuntimeTimeline, final: Path
) -> dict:
    hashes: list[str] = []
    titles = []
    notes = []
    for scene in plan.scenes:
        visual = resolve_scene_visual(paths, scene)
        if visual is None:
            notes.append(f"missing_visual={scene.id}")
            continue
        if is_title_card(scene):
            titles.append(f"{scene.id} {scene.start:.2f}-{scene.end:.2f}s")
        else:
            hashes.append(visual.sha256)
    unique = len(set(hashes))
    dupes = len(hashes) - unique
    black = _black_spans(final)
    notes.append(f"blackdetect_spans={black}")
    stills = [s for s in plan.scenes if not is_title_card(s)]
    long_holds = [s.id for s in stills if s.duration > 7.1]
    if long_holds:
        notes.append(f"holds_over_7s={','.join(long_holds)} (speech-driven, unavoidable)")
    mean = sum(s.duration for s in stills) / len(stills) if stills else 0
    notes.append(f"mean_still_s={mean:.2f} max={max(s.duration for s in stills):.2f}")
    notes.append(f"fingerprint_dupes={duplicate_fingerprints(plan)}")
    return {
        "unique_narrative": unique,
        "duplicate_timeline": dupes,
        "title_cards": len(titles),
        "title_timings": titles,
        "notes": notes,
    }


def _black_spans(path: Path) -> str:
    from docprod.render.ffmpeg import ffmpeg_path

    completed = subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.35:pic_th=0.98",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    hits = re.findall(r"black_start:([-\d.]+)", completed.stderr or "")
    return ",".join(hits) if hits else "none"


def _previous_image_cost(paths: ProjectPaths) -> float | None:
    report = paths.review_dir / "drama_visual_generation_report.json"
    if not report.is_file():
        return None
    payload = json.loads(report.read_text(encoding="utf-8"))
    if payload.get("measured_usd") is not None:
        return float(payload["measured_usd"])
    usages = payload.get("usages") or []
    total = 0.0
    saw = False
    for usage in usages:
        cost = _cost_from_usage(usage if isinstance(usage, dict) else None)
        if cost is not None:
            saw = True
            total += cost
    if saw:
        return round(total, 6)
    if payload.get("estimated_usd") is not None:
        return float(payload["estimated_usd"])
    return None


def _write_qc_markdown(
    paths: ProjectPaths,
    report: DramaProductionReport,
    plan: ScenePlan,
    sound: SoundPlan,
    timeline: RuntimeTimeline,
) -> Path:
    dest = paths.review_dir / "drama_final_qc.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    music_bits = "\n".join(
        f"- {s.music_section_id}: {s.start:.2f}-{s.end:.2f}s {s.purpose}"
        for s in sound.music_sections
    )
    dest.write_text(
        "\n".join(
            [
                "# Birko / Baby Kemal drama — final QC",
                "",
                f"- script runtime (speech): {report.narration_duration:.3f}s",
                f"- scene count: {report.scene_count}",
                f"- unique narrative visuals: {report.unique_narrative_visuals}",
                f"- duplicate timeline assets: {report.duplicate_visuals}",
                f"- title cards: {report.title_card_count}",
                f"- title timings: {', '.join(report.title_timings)}",
                f"- music sections:\n{music_bits}",
                f"- SFX count: {report.sfx_count}",
                f"- chapter stings: {report.chapter_sting_count}",
                f"- ledger-close SFX: {report.ledger_close_present}",
                f"- subtitle cues: {report.subtitle_cue_count}",
                f"- LUFS: {report.lufs}",
                f"- true peak: {report.true_peak}",
                f"- final duration: {report.final_duration:.3f}s",
                f"- new spend this step: ${report.new_paid_spend_usd}",
                f"- previous image cost: {report.previous_image_cost_usd}",
                f"- total estimated episode cost: {report.total_episode_cost_usd}",
                f"- production: {report.production_path}",
                "",
                "## Notes",
                *[f"- {note}" for note in report.notes],
                f"- timeline_duration={timeline.total_duration:.3f}",
                f"- plan_scenes={len(plan.scenes)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return dest


def _final_contact_sheet(paths: ProjectPaths, plan: ScenePlan) -> None:
    entries = []
    for scene in plan.scenes:
        visual = resolve_scene_visual(paths, scene)
        if visual is None:
            continue
        kind = "title" if is_title_card(scene) else "still"
        entries.append((scene.id, kind, visual.path))
    build_contact_sheet(
        paths,
        entries,
        columns=6,
        output=paths.review_dir / "drama_final_contact_sheet.jpg",
    )
