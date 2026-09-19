from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docprod.audio.models import RuntimeTimeline
from docprod.audio.music_prompt import lyria_prompt
from docprod.audio.sound_library import SoundLibrary
from docprod.audio.sound_models import MusicSection, SonicProfile, SoundAsset, SoundPlan
from docprod.audio.sound_plan import build_sound_plan, render_sound_plan_markdown
from docprod.audio.soundtrack_mix import mix_soundtrack, synthesize_generic
from docprod.audio.veo_media import (
    extract_provider_audio,
    mute_and_normalize_visual,
    qc_sync_audio,
)
from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.models.project import Project
from docprod.models.scene import ScenePlan
from docprod.pipeline.inspect_assets import require_zero_placeholders
from docprod.providers.google_lyria import DisabledAdaptiveMusicProvider, GoogleLyriaProvider
from docprod.providers.google_veo import GoogleVeoProvider
from docprod.providers.music_base import MusicGenerateRequest, MusicGenerationProvider
from docprod.providers.pricing import (
    HIGH_VALUE_VIDEO_UNITS,
    LOW_VALUE_VIDEO_UNITS,
    LYRIA_IMAGE_LIMIT,
    MUSIC_HARD_MAX,
    PRICING_VERSION,
    VEO_HARD_REQUESTS,
    VEO_SECONDS_PER_REQUEST,
    lyria_cost_usd,
    veo_cost_usd,
)
from docprod.providers.request_budget import ModelRequestBudget
from docprod.providers.video_base import VideoShotProvider, VideoShotRequest
from docprod.render.ffmpeg import run_ffmpeg
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model, save_json, save_model
from docprod.storage.paths import SCENE_PLAN_FILENAME, ProjectPaths
from docprod.writing.models import NarrationScript

AU_0005_MOTION = (
    "Documentary 16:9 720p. Anonymous warehouse inspection of a maple-syrup barrel. "
    "Subtle gloved hands check a barrel lid. Believable restrained inspection and "
    "controlled weighing context. Worker movement is small and documentary. "
    "Handheld documentary camera, natural warehouse light, no cinematic flourish."
)
AU_0005_AUDIO = (
    "Low warehouse room tone, restrained metal barrel and lid handling, "
    "subtle clothing and foot movement. NO dialogue, NO narration, "
    "NO police-radio audio, NO dramatic cinematic boom."
)
AU_0005_NEGATIVE = (
    "operational theft instructions, readable fake labels, invented logos, "
    "impossible hands, liquid explosion, identifiable historical-person likeness, "
    "dialogue, subtitles"
)
AU_0025_MOTION = (
    "Documentary 16:9 720p. Anonymous barrel sampling and content inspection. "
    "Restrained checking action, plausible industrial barrel interaction, "
    "subtle worker movement, documentary framing. Do not depict a detailed "
    "operational method for siphoning, tampering, replacing contents, or bypassing controls."
)
AU_0025_AUDIO = (
    "Quiet warehouse room tone, restrained tool and container handling, "
    "subtle metal contact. NO dialogue, NO narration, NO exaggerated cinematic impact."
)
AU_0025_NEGATIVE = (
    "detailed theft method, siphoning tutorial, tampering instructions, "
    "readable labels, logos, dialogue, identifiable faces"
)

SHOTS = {
    "au_0005_0006": (AU_0005_MOTION, AU_0005_AUDIO, AU_0005_NEGATIVE),
    "au_0025": (AU_0025_MOTION, AU_0025_AUDIO, AU_0025_NEGATIVE),
}


@dataclass
class Phase11Report:
    dry_run: bool
    video_provider: str
    video_model: str
    video_units: list[str]
    video_seconds: int
    video_cost_usd: float
    music_model: str
    music_sections: int
    music_generation_count: int
    music_reuse_count: int
    music_cost_usd: float
    ambience_cues: int
    event_sfx: int
    transition_stings: int
    silence_spans: int
    sound_cues: int
    veo_candidates_accepted: list[str] = field(default_factory=list)
    veo_candidates_rejected: list[str] = field(default_factory=list)
    realtime_enabled: bool = False
    embedding_matcher: str = "metadata"
    semantic_qc: bool = False
    openai_image: int = 0
    tts: int = 0
    whisper: int = 0
    research: int = 0
    pexels: int = 0
    wikimedia: int = 0
    estimated_total_usd: float = 0.0
    actual_spend_usd: float = 0.0
    production_path: str = ""
    notes: list[str] = field(default_factory=list)
    stopped: bool = False


def produce_episode(
    paths: ProjectPaths,
    project: Project,
    *,
    dry_run: bool,
    confirm_paid: bool,
    settings: Settings | None = None,
    video_provider: VideoShotProvider | None = None,
    music_provider: MusicGenerationProvider | None = None,
    speech_detector=None,
) -> Phase11Report:
    cfg = settings or get_settings()
    plan = load_model(paths.stages_dir / SCENE_PLAN_FILENAME, ScenePlan)
    timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
    script = load_model(paths.story_script_json(), NarrationScript)
    require_zero_placeholders(paths, plan)
    _assert_narration_untouched(paths)
    video_units = list(HIGH_VALUE_VIDEO_UNITS)
    if len(video_units) > VEO_HARD_REQUESTS:
        raise RuntimeError("Veo hard budget is 2 successful requests")
    video_seconds = VEO_SECONDS_PER_REQUEST * len(video_units)
    video_cost = veo_cost_usd(video_seconds)
    library = SoundLibrary(paths.episode_sound_library_json())
    profile = SonicProfile()
    save_model(paths.sonic_profile_json(), profile)
    sound_plan = build_sound_plan(
        project_id=project.id,
        timeline=timeline,
        scenes=plan,
        script=script,
        library=library,
        matcher=cfg.sound_library_matcher,
        profile=profile,
    )
    if sound_plan.generation_required_music > MUSIC_HARD_MAX:
        raise RuntimeError("Music hard max exceeded")
    music_cost = lyria_cost_usd(sound_plan.generation_required_music)
    estimated = round(video_cost + music_cost, 4)
    realtime = DisabledAdaptiveMusicProvider()
    report = Phase11Report(
        dry_run=dry_run,
        video_provider=cfg.video_provider,
        video_model=cfg.video_model,
        video_units=video_units,
        video_seconds=video_seconds,
        video_cost_usd=video_cost,
        music_model=cfg.music_model,
        music_sections=len(sound_plan.music_sections),
        music_generation_count=sound_plan.generation_required_music,
        music_reuse_count=sum(1 for cue in sound_plan.cues if cue.type == "music" and cue.asset_id),
        music_cost_usd=music_cost,
        ambience_cues=sum(1 for cue in sound_plan.cues if cue.type == "ambience"),
        event_sfx=sum(1 for cue in sound_plan.cues if cue.type == "event_sfx"),
        transition_stings=sum(1 for cue in sound_plan.cues if cue.type == "transition_sting"),
        silence_spans=len(sound_plan.silence_spans),
        sound_cues=len(sound_plan.cues),
        realtime_enabled=bool(cfg.enable_lyria_realtime and realtime.is_available()),
        embedding_matcher=cfg.sound_library_matcher,
        semantic_qc=cfg.enable_semantic_audio_qc,
        estimated_total_usd=estimated,
        notes=[
            f"LOW_VALUE remain keyframe preview: {', '.join(LOW_VALUE_VIDEO_UNITS)}",
            f"pricing={PRICING_VERSION}",
            "Lyria RealTime disabled by default",
        ],
    )
    save_model(paths.sound_plan_json(), sound_plan)
    review = render_sound_plan_markdown(sound_plan)
    paths.sound_plan_review_md().write_text(review, encoding="utf-8")
    if estimated > cfg.phase11_max_usd:
        report.stopped = True
        report.notes.append("STOP: estimated spend exceeds PHASE11_MAX_USD")
        return report
    if dry_run:
        return report
    require_paid_call_allowed("google", confirm_paid=confirm_paid, settings=cfg)
    require_gemini_api_key(cfg)
    veo = video_provider or GoogleVeoProvider(settings=cfg)
    lyria = music_provider or GoogleLyriaProvider(settings=cfg)
    video_budget = ModelRequestBudget(VEO_HARD_REQUESTS)
    music_budget = ModelRequestBudget(MUSIC_HARD_MAX)
    accepted: list[str] = []
    rejected: list[str] = []
    for unit_id in video_units:
        video_budget.reserve("veo", 1)
        start_image = _existing_keyframe(paths, unit_id)
        motion, native, negative = SHOTS[unit_id]
        result = veo.generate_shot(
            VideoShotRequest(
                prompt=motion,
                negative_prompt=negative,
                image_path=start_image,
                native_audio_prompt=native,
            ),
            confirm_paid=confirm_paid,
        )
        raw = paths.veo_raw_dir() / f"{unit_id}.mp4"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(result.video_bytes)
        wav = paths.veo_candidate_wav(unit_id)
        extract_provider_audio(raw, wav)
        timing = _unit_duration(timeline, unit_id)
        visual = paths.veo_visual_path(unit_id)
        mute_and_normalize_visual(raw, visual, duration=timing, generated_seconds=8.0)
        qc = qc_sync_audio(wav, speech_detector=speech_detector)
        meta = {
            "asset_unit_id": unit_id,
            "category": "GENERATED_SYNC_AUDIO",
            "source_type": "generated",
            "accepted": qc.accepted,
            "reasons": qc.reasons,
            "license_note": "generated/generic; not archival event audio",
            "start_image": str(start_image),
            "visual_sha256": file_sha256(visual),
        }
        save_json(paths.veo_visual_meta(unit_id), meta)
        save_json(wav.with_suffix(".qc.json"), meta)
        if qc.accepted:
            accepted.append(unit_id)
        else:
            rejected.append(unit_id)
        _stamp_high_value_strategy(plan, unit_id, paths)
    report.veo_candidates_accepted = accepted
    report.veo_candidates_rejected = rejected
    veo_map = {unit: str(paths.veo_candidate_wav(unit)) for unit in accepted}
    sound_plan = build_sound_plan(
        project_id=project.id,
        timeline=timeline,
        scenes=plan,
        script=script,
        library=library,
        matcher=cfg.sound_library_matcher,
        veo_candidates=veo_map,
        profile=profile,
    )
    _fill_lyria_prompts(sound_plan, profile, paths, plan)
    assets = _materialize_audio(
        paths,
        sound_plan,
        library,
        lyria,
        music_budget,
        confirm_paid=confirm_paid,
        project_id=project.id,
        veo_map=veo_map,
    )
    save_model(paths.sound_plan_json(), sound_plan)
    review = render_sound_plan_markdown(sound_plan)
    paths.sound_plan_review_md().write_text(review, encoding="utf-8")
    library.save()
    loudness = mix_soundtrack(
        narration=paths.narration_master_wav(),
        plan=sound_plan,
        assets=assets,
        dest=paths.production_mix_wav(),
        timeline=timeline,
    )
    production = _render_production_v1(paths, timeline, video_units)
    report.production_path = str(production)
    report.actual_spend_usd = round(
        veo_cost_usd(VEO_SECONDS_PER_REQUEST * video_budget.used_requests)
        + lyria_cost_usd(music_budget.used_requests),
        4,
    )
    report.music_generation_count = music_budget.used_requests
    report.sound_cues = len(sound_plan.cues)
    save_json(
        paths.review_dir / "phase11_costs.json",
        {
            "pricing_version": PRICING_VERSION,
            "actual_spend_usd": report.actual_spend_usd,
            "reference_cost_usd": estimated,
            "optional_future_cost": {"lyria_realtime": None, "clip": 0.04},
            "loudness": loudness,
            "veo_requests": video_budget.used_requests,
            "lyria_requests": music_budget.used_requests,
        },
    )
    save_model(paths.stages_dir / SCENE_PLAN_FILENAME, plan)
    return report


def _assert_narration_untouched(paths: ProjectPaths) -> None:
    master = paths.narration_master_wav()
    if not master.is_file():
        raise FileNotFoundError("master.wav missing; Phase 11 must not regenerate narration")


def _existing_keyframe(paths: ProjectPaths, unit_id: str) -> Path:
    for suffix in (".jpg", ".jpeg", ".png"):
        candidate = paths.ai_keyframe_path(unit_id, suffix)
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Existing keyframe missing for {unit_id}")


def _unit_duration(timeline: RuntimeTimeline, unit_id: str) -> float:
    members = [item for item in timeline.scenes if item.asset_unit_id == unit_id]
    if not members:
        return 8.0
    return max(item.end for item in members) - min(item.start for item in members)


def _stamp_high_value_strategy(plan: ScenePlan, unit_id: str, paths: ProjectPaths) -> None:
    scenes = []
    for scene in plan.scenes:
        if str(scene.metadata.get("asset_unit_id") or "") != unit_id:
            scenes.append(scene)
            continue
        meta = dict(scene.metadata)
        meta["runtime_preview_strategy"] = "ai_video"
        meta["source_path"] = str(paths.veo_visual_path(unit_id).relative_to(paths.root))
        scenes.append(scene.model_copy(update={"metadata": meta}))
    plan.__dict__["scenes"] = scenes


def _fill_lyria_prompts(
    sound_plan: SoundPlan,
    profile: SonicProfile,
    paths: ProjectPaths,
    scenes: ScenePlan,
) -> None:
    by_id = {scene.id: scene for scene in scenes.scenes}
    for section in sound_plan.music_sections:
        frames = _visual_frames(paths, section, by_id)
        section.visual_context_frames = [str(path) for path in frames]
        section.generation_prompt = lyria_prompt(section, profile)


def _visual_frames(paths: ProjectPaths, section: MusicSection, scenes: dict) -> list[Path]:
    frames: list[Path] = []
    for scene_id in section.visual_context_scene_ids:
        scene = scenes.get(scene_id)
        if scene is None:
            continue
        unit = str(scene.metadata.get("asset_unit_id") or "")
        for candidate in (
            paths.ai_keyframe_path(unit),
            paths.scene_image_path(scene_id),
        ):
            if candidate.is_file() and candidate not in frames:
                frames.append(candidate)
                break
        if len(frames) >= LYRIA_IMAGE_LIMIT:
            break
    return frames[:LYRIA_IMAGE_LIMIT]


def _materialize_audio(
    paths: ProjectPaths,
    sound_plan: SoundPlan,
    library: SoundLibrary,
    lyria: MusicGenerationProvider,
    budget: ModelRequestBudget,
    *,
    confirm_paid: bool,
    project_id: str,
    veo_map: dict[str, str],
) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    for section in sound_plan.music_sections:
        if section.library_asset_id:
            existing = library.get(section.library_asset_id)
            if existing and existing.local_path:
                assets[section.music_section_id] = Path(existing.local_path)
                assets[existing.asset_id] = Path(existing.local_path)
                continue
        budget.reserve("lyria", 1)
        frames = [Path(item) for item in section.visual_context_frames if Path(item).is_file()]
        result = lyria.generate_music(
            MusicGenerateRequest(
                prompt=section.generation_prompt,
                duration_hint_seconds=section.end - section.start,
                image_paths=frames[:LYRIA_IMAGE_LIMIT],
            ),
            confirm_paid=confirm_paid,
        )
        dest = paths.soundtrack_dir() / f"{section.music_section_id}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(result.audio_bytes)
        _normalize_wav(dest)
        asset = SoundAsset(
            asset_id=section.music_section_id,
            category="MUSIC_BED",
            source_type="generated",
            provider=result.provider,
            model=result.model,
            prompt=section.generation_prompt,
            duration=section.end - section.start,
            tags=["documentary", "instrumental"],
            moods=[section.mood],
            reuse_allowed=True,
            generated_provenance=f"{result.provider}:{result.model}",
            sha256=file_sha256(dest),
            local_path=str(dest),
            reuse_class="channel_reusable",
            notes="SynthID/generated provenance recorded; not archival.",
        )
        library.add(asset)
        library.mark_used(asset.asset_id, project_id)
        section.library_asset_id = asset.asset_id
        section.status = "generated"
        assets[section.music_section_id] = dest
        assets[asset.asset_id] = dest
        for cue in sound_plan.cues:
            if cue.sound_need_id == section.music_section_id:
                cue.asset_id = asset.asset_id
                cue.generated_or_reused = "generated"
                cue.status = "ready"
    for cue in sound_plan.cues:
        if cue.type == "music":
            continue
        if cue.generated_or_reused == "veo_candidate":
            path = Path(veo_map.get(cue.asset_id, ""))
            if path.is_file():
                assets[cue.sound_need_id] = path
                continue
        if cue.type == "ambience":
            kind = "ambience"
        elif cue.type == "transition_sting":
            kind = "sting"
        else:
            kind = "metal"
        dest = paths.soundtrack_dir() / f"{cue.cue_id}.wav"
        synthesize_generic(kind, dest, duration=max(0.3, cue.end - cue.start))
        asset = SoundAsset(
            asset_id=cue.cue_id,
            category="AMBIENCE"
            if cue.type == "ambience"
            else "TRANSITION_STING"
            if cue.type == "transition_sting"
            else "EVENT_SFX",
            source_type="local_generic",
            prompt=cue.story_reason,
            duration=cue.end - cue.start,
            reuse_allowed=True,
            license_note="generated/generic; not archival event audio",
            sha256=file_sha256(dest),
            local_path=str(dest),
            reuse_class="generic_reusable",
        )
        library.add(asset)
        cue.asset_id = asset.asset_id
        cue.generated_or_reused = "generated_local"
        cue.status = "ready"
        assets[cue.sound_need_id] = dest
        assets[asset.asset_id] = dest
    return assets


def _normalize_wav(path: Path) -> None:
    tmp = path.with_suffix(".norm.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(path),
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(tmp),
            ],
            timeout=60,
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _render_production_v1(
    paths: ProjectPaths, timeline: RuntimeTimeline, units: list[str]
) -> Path:
    base = paths.preview_visual_v3_mp4()
    if not base.is_file():
        raise FileNotFoundError("documentary_preview_visual_v3.mp4 is required")
    dest = paths.production_v1_mp4()
    dest.parent.mkdir(parents=True, exist_ok=True)
    overlays: list[tuple[Path, float, float]] = []
    for unit in units:
        clip = paths.veo_visual_path(unit)
        if not clip.is_file():
            continue
        members = [item for item in timeline.scenes if item.asset_unit_id == unit]
        if not members:
            continue
        start = min(item.start for item in members)
        end = max(item.end for item in members)
        overlays.append((clip, start, end))
    args: list[str] = ["-i", str(base)]
    for clip, _s, _e in overlays:
        args.extend(["-i", str(clip)])
    args.extend(["-i", str(paths.production_mix_wav())])
    filter_parts: list[str] = []
    last = "[0:v]"
    for index, (_clip, start, end) in enumerate(overlays, start=1):
        label = f"v{index}"
        out = f"o{index}"
        filter_parts.append(
            f"[{index}:v]scale=1280:720,setpts=PTS-STARTPTS+{start:.4f}/TB[{label}]"
        )
        filter_parts.append(
            f"{last}[{label}]overlay=enable='between(t,{start:.4f},{end:.4f})'[{out}]"
        )
        last = f"[{out}]"
    audio_index = 1 + len(overlays)
    subtitle = paths.captions_narrated_ass()
    vf_end = last
    if subtitle.is_file():
        from docprod.render.ffmpeg import escape_filter_path

        filter_parts.append(f"{last}subtitles='{escape_filter_path(subtitle)}'[vout]")
        vf_end = "[vout]"
    tmp = dest.with_suffix(".tmp.mp4")
    try:
        cmd = [
            *args,
            "-filter_complex",
            ";".join(filter_parts) if filter_parts else "null",
            "-map",
            vf_end,
            "-map",
            f"{audio_index}:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(tmp),
        ]
        if not overlays and not subtitle.is_file():
            cmd = [
                "-i",
                str(base),
                "-i",
                str(paths.production_mix_wav()),
                "-c:v",
                "copy",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:a",
                "aac",
                "-shortest",
                str(tmp),
            ]
        run_ffmpeg(cmd, timeout=600)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest
