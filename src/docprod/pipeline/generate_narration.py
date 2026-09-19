from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docprod.audio.align import align_script_to_whisper
from docprod.audio.chunks import NarrationChunkPlanner, validate_chunk_manifest
from docprod.audio.join import (
    JoinResult,
    concat_chunk_wavs,
    format_normalize_wav,
    join_target_seconds,
)
from docprod.audio.mix import apply_loudnorm_wav, measure_loudnorm
from docprod.audio.models import (
    DEFAULT_VOICE_INSTRUCTIONS,
    AlignmentReport,
    CanonicalNarrationScript,
    ChunkAudioWindow,
    NarrationChunkManifest,
    NarrationMasterMeta,
    RuntimeTimeline,
    WhisperWord,
)
from docprod.audio.script import build_canonical_script, tokenize_display
from docprod.audio.timeline import apply_runtime_timeline, build_runtime_timeline
from docprod.config import Settings, get_settings
from docprod.models.project import Project
from docprod.models.scene import ScenePlan
from docprod.providers.openai_tts import OpenAITTSProvider, tts_request_hash
from docprod.providers.openai_whisper import OpenAIWhisperAligner
from docprod.providers.request_budget import ModelRequestBudget
from docprod.render.ffmpeg import probe_media, run_ffmpeg
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
    word_count: int
    output_wav: Path
    chunk_manifest: NarrationChunkManifest
    tts_requests: int
    whisper_requests: int
    image_requests: int = 0
    video_requests: int = 0
    chunk_previews: list[str] = field(default_factory=list)


@dataclass
class NarrationResult:
    script: CanonicalNarrationScript
    meta: NarrationMasterMeta
    alignment: AlignmentReport
    timeline: RuntimeTimeline
    tts_request_count: int
    whisper_request_count: int
    loudness: dict[str, str] | None = None
    chunk_manifest: NarrationChunkManifest | None = None


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
    manifest = NarrationChunkPlanner().plan(script, plan)
    validate_chunk_manifest(manifest, script)
    paths.narration_chunks_dir().mkdir(parents=True, exist_ok=True)
    save_model(paths.narration_proposed_chunk_plan(), manifest)
    if not paths.narration_chunk_manifest().is_file():
        save_model(paths.narration_chunk_manifest(), manifest)
    previews = []
    if manifest.chunks:
        first = manifest.chunks[0].text.strip()
        last_sentence = first.split(".")[-2:] if "." in first else [first[-120:]]
        previews.append(" ".join(part.strip() for part in last_sentence if part.strip())[-180:])
    if len(manifest.chunks) > 1:
        second = manifest.chunks[1].text.strip()
        first_sentence = second.split(".", 1)[0].strip()
        previews.append(first_sentence[:180])
    return NarrationDryRun(
        script=script,
        provider="openai",
        model=cfg.openai_tts_model,
        voice=cfg.openai_tts_voice,
        speed=cfg.openai_tts_speed,
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
        character_count=len(script.text),
        word_count=len(tokenize_display(script.text)),
        output_wav=paths.narration_master_wav(),
        chunk_manifest=manifest,
        tts_requests=manifest.chunk_count,
        whisper_requests=1,
        image_requests=0,
        video_requests=0,
        chunk_previews=previews,
    )


def _merge_usage(parts: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    merged: dict[str, float] = {}
    found = False
    for usage in parts:
        if not usage:
            continue
        found = True
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                merged[str(key)] = merged.get(str(key), 0.0) + float(value)
    return merged if found else None


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
    cfg = settings or get_settings()
    _ = project
    prepared = prepare_narration(paths, plan, settings=cfg)
    script = prepared.script
    manifest = prepared.chunk_manifest
    if paths.narration_chunk_manifest().is_file() and paths.narration_chunk_wav(1).is_file():
        manifest = load_model(paths.narration_chunk_manifest(), NarrationChunkManifest)
    script_hash = content_hash(script.text)
    request_hash = tts_request_hash(
        model=cfg.openai_tts_model,
        voice=cfg.openai_tts_voice,
        speed=cfg.openai_tts_speed,
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
        script=script.text + f"|chunks={manifest.chunk_count}",
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
                chunk_manifest=manifest,
            )
    tts_client = tts or OpenAITTSProvider(settings=cfg)
    whisper_client = whisper or OpenAIWhisperAligner(settings=cfg)
    paid_needed = 0
    for spec in manifest.chunks:
        out = paths.narration_chunk_wav(spec.chunk_index)
        meta_file = paths.narration_chunk_meta(spec.chunk_index)
        chunk_hash = tts_request_hash(
            model=cfg.openai_tts_model,
            voice=cfg.openai_tts_voice,
            speed=cfg.openai_tts_speed,
            instructions=spec.instructions,
            script=spec.text,
        )
        if out.is_file() and meta_file.is_file():
            existing_meta = json.loads(meta_file.read_text())
            if existing_meta.get("request_hash") == chunk_hash and existing_meta.get(
                "sha256"
            ) == file_sha256(out):
                continue
        paid_needed += 1
    budget = ModelRequestBudget(paid_needed)
    usages: list[dict[str, Any] | None] = []
    chunk_wavs: list[Path] = []
    chunk_durations: list[float] = []
    for spec in manifest.chunks:
        out = paths.narration_chunk_wav(spec.chunk_index)
        meta_file = paths.narration_chunk_meta(spec.chunk_index)
        chunk_hash = tts_request_hash(
            model=cfg.openai_tts_model,
            voice=cfg.openai_tts_voice,
            speed=cfg.openai_tts_speed,
            instructions=spec.instructions,
            script=spec.text,
        )
        if out.is_file() and meta_file.is_file():
            existing_meta = json.loads(meta_file.read_text())
            if existing_meta.get("request_hash") == chunk_hash and existing_meta.get(
                "sha256"
            ) == file_sha256(out):
                usages.append(existing_meta.get("usage"))
                chunk_wavs.append(out)
                chunk_durations.append(
                    float(existing_meta.get("duration") or probe_media(out).duration)
                )
                continue
        budget.reserve("tts")
        raw_bytes, usage = tts_client.synthesize(
            spec.text,
            confirm_paid=confirm_paid,
            instructions=spec.instructions,
            max_attempts=1,
        )
        usages.append(usage)
        raw_path = paths.narration_chunks_dir() / f"{spec.chunk_id}.raw.wav"
        atomic_write_bytes(raw_path, raw_bytes)
        out = paths.narration_chunk_wav(spec.chunk_index)
        format_normalize_wav(raw_path, out)
        raw_path.unlink(missing_ok=True)
        probe = probe_media(out)
        chunk_wavs.append(out)
        chunk_durations.append(probe.duration)
        save_json(
            paths.narration_chunk_meta(spec.chunk_index),
            {
                "chunk_id": spec.chunk_id,
                "model": cfg.openai_tts_model,
                "voice": cfg.openai_tts_voice,
                "speed": cfg.openai_tts_speed,
                "instructions_hash": content_hash(spec.instructions),
                "script_span": [spec.char_start, spec.char_end],
                "request_hash": chunk_hash,
                "duration": probe.duration,
                "sample_rate": probe.sample_rate or 48000,
                "channels": probe.channels or 1,
                "sha256": file_sha256(out),
                "usage": usage,
            },
        )
    reused_master = wav.is_file()
    if not reused_master:
        from docprod.pipeline.narration_gates import gate_master_promotion, inspect_chunk_integrity

        gate_master_promotion(inspect_chunk_integrity(paths, manifest, run_acoustic=True))
    join: JoinResult
    loud_in: dict[str, str]
    loud_out: dict[str, str]
    if reused_master:
        probe = probe_media(wav)
        scale = probe.duration / (sum(chunk_durations) or 1.0)
        windows: list[tuple[float, float]] = []
        joins: list[float] = []
        cursor = 0.0
        scaled: list[float] = []
        for index, duration in enumerate(chunk_durations):
            span = duration * scale
            if index > 0:
                kind = manifest.chunks[index].boundary_type
                joins.append(round(join_target_seconds(kind), 4))
            windows.append((round(cursor, 4), round(cursor + span, 4)))
            cursor += span
            scaled.append(span)
        join = JoinResult(
            join_silences=joins, part_durations=scaled, audio_windows=windows
        )
        loud_out = measure_loudnorm(wav)
        loud_in = dict(loud_out)
        probe = probe_media(paths.narration_master_wav())
    else:
        concat_raw = paths.narration_dir / "master.concat.wav"
        join = concat_chunk_wavs(
            chunk_wavs,
            concat_raw,
            boundary_types=[item.boundary_type for item in manifest.chunks],
        )
        loud_in, loud_out = apply_loudnorm_wav(concat_raw, paths.narration_master_wav())
        concat_raw.unlink(missing_ok=True)
        probe = probe_media(paths.narration_master_wav())
    raw_whisper: dict
    language: str | None
    if paths.whisper_alignment_json().is_file():
        raw_whisper = json.loads(paths.whisper_alignment_json().read_text())
        words = [
            WhisperWord(
                word=str(item.get("word") or "").strip(),
                start=float(item.get("start") or 0.0),
                end=float(item.get("end") or 0.0),
            )
            for item in raw_whisper.get("words") or []
            if str(item.get("word") or "").strip()
        ]
        language = str(raw_whisper.get("language") or "tr")
    else:
        from docprod.pipeline.narration_gates import (
            assert_whisper_allowed,
            build_whisper_preflight,
        )

        preflight = build_whisper_preflight(
            paths,
            canonical_word_count=len(tokenize_display(script.text)),
        )
        assert_whisper_allowed(preflight)
        whisper_input = paths.narration_dir / "whisper_input.mp3"
        run_ffmpeg(
            [
                "-i",
                str(paths.narration_master_wav()),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(whisper_input),
            ],
            timeout=180,
        )
        words, language, raw_whisper = whisper_client.align_words(
            whisper_input,
            confirm_paid=confirm_paid,
            language="tr",
        )
        whisper_dur = probe_media(whisper_input).duration
        if whisper_dur > 0.1 and abs(whisper_dur - probe.duration) > 0.05:
            scale = probe.duration / whisper_dur
            words = [
                item.model_copy(update={"start": item.start * scale, "end": item.end * scale})
                for item in words
            ]
        whisper_input.unlink(missing_ok=True)
        save_json(paths.whisper_alignment_json(), raw_whisper)
    windows = None
    if not reused_master:
        windows = [
            ChunkAudioWindow(
                word_start=spec.word_start,
                word_end=spec.word_end,
                audio_start=window[0],
                audio_end=window[1],
            )
            for spec, window in zip(manifest.chunks, join.audio_windows, strict=True)
        ]
    alignment = align_script_to_whisper(
        plan,
        words,
        language=language,
        require_quality=True,
        audio_duration=probe.duration,
        chunk_windows=windows,
    )
    last_speech = max((float(token.end) for token in alignment.tokens if token.end), default=0.0)
    if last_speech > 1.0 and probe.duration - last_speech > 25.0:
        trimmed_end = round(last_speech + 0.55, 3)
        tmp = paths.narration_dir / "master.trimmed.wav"
        run_ffmpeg(
            [
                "-i",
                str(paths.narration_master_wav()),
                "-t",
                f"{trimmed_end:.3f}",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(tmp),
            ],
            timeout=180,
        )
        tmp.replace(paths.narration_master_wav())
        probe = probe_media(paths.narration_master_wav())
        loud_out = measure_loudnorm(paths.narration_master_wav())
        loud_in = dict(loud_out)
    save_model(paths.narration_alignment_json(), alignment)
    timeline = build_runtime_timeline(plan, alignment, audio_duration=probe.duration)
    save_model(paths.runtime_timeline_json(), timeline)
    loudness = {**loud_in, **{f"output_{k}": v for k, v in loud_out.items()}}
    if loud_out.get("input_i"):
        loudness["output_i"] = loud_out.get("input_i", "")
        loudness["output_tp"] = loud_out.get("input_tp", "")
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
        usage=_merge_usage(usages),
        loudness=loudness or None,
        generation_status="success",
        tts_request_count=tts_client.request_count
        or (manifest.chunk_count if reused_master else 0),
        whisper_request_count=whisper_client.request_count
        or (1 if paths.whisper_alignment_json().is_file() else 0),
        chunk_count=manifest.chunk_count,
        chunk_durations=chunk_durations,
        join_silences=join.join_silences,
        loudness_input=loud_in or None,
    )
    save_model(paths.narration_master_meta(), meta)
    return NarrationResult(
        script=script,
        meta=meta,
        alignment=alignment,
        timeline=timeline,
        tts_request_count=tts_client.request_count,
        whisper_request_count=whisper_client.request_count,
        loudness=loudness,
        chunk_manifest=manifest,
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
            rel = str(scene.metadata.get("source_path") or "")
            if rel:
                nested = paths.root / rel
                source = nested if nested.is_file() else source
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
