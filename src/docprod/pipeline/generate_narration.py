from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docprod.audio.align import align_script_to_whisper
from docprod.audio.mix import measure_loudnorm, normalize_master_wav
from docprod.audio.models import (
    DEFAULT_VOICE_INSTRUCTIONS,
    AlignmentReport,
    CanonicalNarrationScript,
    NarrationMasterMeta,
    RuntimeTimeline,
)
from docprod.audio.script import build_canonical_script
from docprod.audio.timeline import apply_runtime_timeline, build_runtime_timeline
from docprod.config import Settings, get_settings
from docprod.models.project import Project
from docprod.models.scene import ScenePlan
from docprod.providers.openai_tts import OpenAITTSProvider, tts_request_hash
from docprod.providers.openai_whisper import OpenAIWhisperAligner
from docprod.render.ffmpeg import probe_media
from docprod.render.still import STOCK_STRATEGIES
from docprod.stock.downloader import reclip_stock_to_duration
from docprod.stock.models import StockSourceManifest
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import (
    atomic_write_bytes,
    atomic_write_text,
    load_model,
    save_json,
    save_model,
)
from docprod.storage.paths import ProjectPaths


@dataclass
class NarrationDryRun:
    script: CanonicalNarrationScript
    provider: str
    model: str
    voice: str
    speed: float
    instructions: str
    character_count: int
    output_wav: Path


@dataclass
class NarrationResult:
    script: CanonicalNarrationScript
    meta: NarrationMasterMeta
    alignment: AlignmentReport
    timeline: RuntimeTimeline
    tts_request_count: int
    whisper_request_count: int
    loudness: dict[str, str] | None = None


def persist_canonical_script(paths: ProjectPaths, script: CanonicalNarrationScript) -> None:
    paths.narration_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(paths.narration_script_txt(), script.text + "\n")
    save_model(paths.narration_script_spans(), script)


def prepare_narration(
    paths: ProjectPaths,
    plan: ScenePlan,
    *,
    settings: Settings | None = None,
) -> NarrationDryRun:
    cfg = settings or get_settings()
    script = build_canonical_script(plan)
    persist_canonical_script(paths, script)
    return NarrationDryRun(
        script=script,
        provider="openai",
        model=cfg.openai_tts_model,
        voice=cfg.openai_tts_voice,
        speed=cfg.openai_tts_speed,
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
        character_count=len(script.text),
        output_wav=paths.narration_master_wav(),
    )


def generate_narration(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    confirm_paid: bool,
    settings: Settings | None = None,
    tts: OpenAITTSProvider | None = None,
    whisper: OpenAIWhisperAligner | None = None,
) -> NarrationResult:
    from docprod.audio.tts_preflight import require_tts_within_limit

    cfg = settings or get_settings()
    _ = project
    prepared = prepare_narration(paths, plan, settings=cfg)
    script = prepared.script
    require_tts_within_limit(script.text)
    script_hash = content_hash(script.text)
    request_hash = tts_request_hash(
        model=cfg.openai_tts_model,
        voice=cfg.openai_tts_voice,
        speed=cfg.openai_tts_speed,
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
        script=script.text,
    )
    wav = paths.narration_master_wav()
    meta_path = paths.narration_master_meta()
    align_path = paths.narration_alignment_json()
    if wav.is_file() and meta_path.is_file() and align_path.is_file():
        existing = load_model(meta_path, NarrationMasterMeta)
        if existing.request_hash == request_hash and existing.output_sha256 == file_sha256(wav):
            alignment = load_model(align_path, AlignmentReport)
            if paths.runtime_timeline_json().is_file():
                timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
            else:
                probe = probe_media(wav)
                timeline = build_runtime_timeline(
                    plan, alignment, audio_duration=probe.duration
                )
                save_model(paths.runtime_timeline_json(), timeline)
            return NarrationResult(
                script=script,
                meta=existing.model_copy(
                    update={"tts_request_count": 0, "whisper_request_count": 0}
                ),
                alignment=alignment,
                timeline=timeline,
                tts_request_count=0,
                whisper_request_count=0,
                loudness=existing.loudness,
            )
    tts_client = tts or OpenAITTSProvider(settings=cfg)
    whisper_client = whisper or OpenAIWhisperAligner(settings=cfg)
    raw_bytes, usage = tts_client.synthesize(
        script.text,
        confirm_paid=confirm_paid,
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
    )
    raw_path = paths.narration_dir / "master.raw.wav"
    atomic_write_bytes(raw_path, raw_bytes)
    normalize_master_wav(raw_path, paths.narration_master_wav())
    raw_path.unlink(missing_ok=True)
    probe = probe_media(paths.narration_master_wav())
    script_hash = content_hash(script.text)
    words, language, raw_whisper = whisper_client.align_words(
        paths.narration_master_wav(),
        confirm_paid=confirm_paid,
        language="tr",
    )
    save_json(paths.whisper_alignment_json(), raw_whisper)
    alignment = align_script_to_whisper(
        plan, words, language=language, require_quality=True, audio_duration=probe.duration
    )
    save_model(paths.narration_alignment_json(), alignment)
    timeline = build_runtime_timeline(plan, alignment, audio_duration=probe.duration)
    save_model(paths.runtime_timeline_json(), timeline)
    meta = NarrationMasterMeta(
        provider="openai",
        model=cfg.openai_tts_model,
        voice=cfg.openai_tts_voice,
        speed=cfg.openai_tts_speed,
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
        script_hash=script_hash,
        request_hash=request_hash,
        duration=probe.duration,
        sample_rate=probe.sample_rate or 48000,
        channels=probe.channels or 1,
        output_sha256=file_sha256(paths.narration_master_wav()),
        usage=usage,
        loudness=measure_loudnorm(paths.narration_master_wav()) or None,
        generation_status="success",
        tts_request_count=tts_client.request_count,
        whisper_request_count=whisper_client.request_count,
    )
    save_model(paths.narration_master_meta(), meta)
    return NarrationResult(
        script=script,
        meta=meta,
        alignment=alignment,
        timeline=timeline,
        tts_request_count=tts_client.request_count,
        whisper_request_count=whisper_client.request_count,
    )


def retime_stock_for_runtime(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    seed: int,
) -> None:
    for scene in plan.scenes:
        if scene.asset_strategy not in STOCK_STRATEGIES:
            continue
        source = paths.stock_source_mp4(scene.id)
        if not source.is_file():
            raise FileNotFoundError(f"Missing stock source for {scene.id}")
        start, sha = reclip_stock_to_duration(
            source,
            paths.stock_clip_mp4(scene.id),
            needed=float(scene.duration),
            seed=seed,
            scene_id=scene.id,
        )
        meta_path = paths.stock_source_meta(scene.id)
        if meta_path.is_file():
            meta = load_model(meta_path, StockSourceManifest)
            save_model(
                meta_path,
                meta.model_copy(
                    update={
                        "clip_start": start,
                        "clip_duration": float(scene.duration),
                        "clip_sha256": sha,
                    }
                ),
            )


def load_runtime_plan(paths: ProjectPaths, plan: ScenePlan) -> ScenePlan:
    timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
    return apply_runtime_timeline(plan, timeline)
