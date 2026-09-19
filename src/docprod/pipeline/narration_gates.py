from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from docprod.audio.duplicates import detect_repeated_audio
from docprod.audio.integrity import (
    WHISPER_USD_PER_MINUTE,
    TTSChunkIntegrityResult,
    assert_promotable,
    evaluate_chunk_integrity,
    evaluate_master_duration,
)
from docprod.audio.models import NarrationChunkManifest
from docprod.audio.script import tokenize_display
from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import IntegrityBlockedError
from docprod.providers.openai_tts import OpenAITTSProvider
from docprod.render.ffmpeg import probe_media
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import save_json
from docprod.storage.paths import ProjectPaths


@dataclass
class WhisperPreflight:
    allowed: bool
    audio_duration: float
    expected_duration: float
    estimated_minutes: float
    estimated_whisper_usd: float
    chunk_statuses: list[dict[str, Any]] = field(default_factory=list)
    master_status: str = "PASS"
    repaired: bool = False
    reasons: list[str] = field(default_factory=list)


def inspect_chunk_integrity(
    paths: ProjectPaths,
    manifest: NarrationChunkManifest,
    *,
    run_acoustic: bool = True,
) -> list[TTSChunkIntegrityResult]:
    results: list[TTSChunkIntegrityResult] = []
    prior: list[float] = []
    for spec in manifest.chunks:
        wav = paths.narration_chunk_wav(spec.chunk_index)
        if not wav.is_file():
            continue
        duration = probe_media(wav).duration
        words = spec.word_end - spec.word_start
        result = evaluate_chunk_integrity(
            chunk_id=spec.chunk_id,
            word_count=words,
            character_count=spec.character_count,
            duration=duration,
            prior_wpm=prior or None,
        )
        if run_acoustic and result.status != "PASS":
            dup = detect_repeated_audio(wav)
            result.reasons.append(f"acoustic:{dup.status}:{dup.reason}")
            if dup.status == "FAIL":
                result.status = "FAIL"
        results.append(result)
        if result.status == "PASS":
            prior.append(result.wpm)
        save_json(paths.narration_chunk_integrity(spec.chunk_id), asdict(result))
    return results


def record_historical_maple_repair(paths: ProjectPaths) -> dict[str, Any]:
    """Document the existing local trim; do not rewrite audio."""
    payload = {
        "source_chunk": "chunk_002",
        "integrity_status_original": "FAIL",
        "reason": "repeated narration / anomalous duration",
        "repair_type": "local_duplicate_tail_trim",
        "raw_chunk_002_duration": 366.2,
        "raw_master_duration": 616.31,
        "promoted_canonical_end": 430.87,
        "repair_range": {"discard_start": 430.87, "discard_end": 616.31},
        "repair_reason": (
            "Chunk 2 spoke its supplied text twice. Whisper saw the canonical "
            "ending near 430s then a restart from 2012. Tail trimmed locally."
        ),
        "human_or_detector_confirmation": "detector_duration_and_whisper_repeat",
        "original_chunk_preserved": True,
        "silent_repair": False,
    }
    save_json(paths.narration_master_repair_json(), payload)
    save_json(
        paths.narration_chunk_integrity("chunk_002"),
        asdict(
            TTSChunkIntegrityResult(
                chunk_id="chunk_002",
                word_count=372,
                character_count=2562,
                duration=366.2,
                wpm=60.95,
                duration_per_word=0.9844,
                expected_duration=193.9,
                duration_ratio=1.889,
                status="FAIL",
                reasons=["historical duplicated chunk", "wpm 60.9 vs chunk1 ~115"],
                sibling_median_wpm=115.1,
                recovery_actions=["LOCAL_TRIM_CONFIRMED_DUPLICATE", "RETRY_CHUNK"],
            )
        ),
    )
    if paths.narration_chunk_wav(1).is_file():
        dur = probe_media(paths.narration_chunk_wav(1)).duration
        save_json(
            paths.narration_chunk_integrity("chunk_001"),
            asdict(
                evaluate_chunk_integrity(
                    chunk_id="chunk_001",
                    word_count=480,
                    character_count=3569,
                    duration=dur,
                )
            ),
        )
    return payload


def build_whisper_preflight(
    paths: ProjectPaths,
    *,
    canonical_word_count: int,
    observed_wpm: float | None = None,
) -> WhisperPreflight:
    wav = paths.narration_master_wav()
    duration = probe_media(wav).duration if wav.is_file() else 0.0
    wpm = observed_wpm or 115.0
    master = evaluate_master_duration(
        canonical_word_count=canonical_word_count,
        actual_duration=duration,
        observed_wpm=wpm,
    )
    chunk_rows: list[dict[str, Any]] = []
    blocked = False
    for path in sorted(paths.narration_chunks_dir().glob("chunk_*.integrity.json")):
        data = json.loads(path.read_text())
        chunk_rows.append(data)
        if data.get("status") == "FAIL":
            blocked = True
    repaired = paths.narration_master_repair_json().is_file()
    allowed = True
    reasons = list(master.reasons)
    if blocked and not repaired:
        allowed = False
        reasons.append("FAIL TTS chunk without approved repaired master")
    if master.blocks_whisper() and not repaired:
        allowed = False
    if repaired and wav.is_file():
        allowed = True
        reasons.append("approved repaired master present")
    minutes = duration / 60.0
    preflight = WhisperPreflight(
        allowed=allowed,
        audio_duration=round(duration, 3),
        expected_duration=master.expected_duration,
        estimated_minutes=round(minutes, 4),
        estimated_whisper_usd=round(minutes * WHISPER_USD_PER_MINUTE, 6),
        chunk_statuses=chunk_rows,
        master_status=master.status,
        repaired=repaired,
        reasons=reasons,
    )
    save_json(paths.whisper_preflight_json(), asdict(preflight))
    return preflight


def assert_whisper_allowed(preflight: WhisperPreflight) -> None:
    if not preflight.allowed:
        raise IntegrityBlockedError("Whisper preflight blocked: " + "; ".join(preflight.reasons))


def next_chunk_version(directory: Path) -> int:
    existing = [int(path.stem[1:]) for path in directory.glob("v*.wav") if path.stem[1:].isdigit()]
    return (max(existing) if existing else 0) + 1


def retry_narration_chunk(
    paths: ProjectPaths,
    chunk_id: str,
    *,
    text: str,
    instructions: str,
    confirm_paid: bool,
    settings: Settings | None = None,
    tts: OpenAITTSProvider | None = None,
) -> Path:
    cfg = settings or get_settings()
    require_paid_call_allowed("openai", confirm_paid=confirm_paid, settings=cfg)
    versions = paths.narration_chunk_versions_dir(chunk_id)
    versions.mkdir(parents=True, exist_ok=True)
    index = int(chunk_id.rsplit("_", 1)[-1])
    original = paths.narration_chunk_wav(index)
    original_sha = file_sha256(original) if original.is_file() else ""
    archive = versions / "v001.wav"
    if original.is_file() and not archive.is_file():
        shutil.copy2(original, archive)
        meta = paths.narration_chunk_meta(index)
        if meta.is_file():
            shutil.copy2(meta, versions / "v001.meta.json")
    client = tts or OpenAITTSProvider(settings=cfg)
    raw, usage = client.synthesize(
        text, confirm_paid=confirm_paid, instructions=instructions, max_attempts=1
    )
    version = next_chunk_version(versions)
    dest = versions / f"v{version:03d}.wav"
    dest.write_bytes(raw)
    try:
        duration = probe_media(dest).duration
    except Exception:  # noqa: BLE001
        duration = 0.0
    words = len(tokenize_display(text))
    result = evaluate_chunk_integrity(
        chunk_id=f"{chunk_id}_v{version:03d}",
        word_count=words,
        character_count=len(text),
        duration=duration,
    )
    save_json(
        versions / f"v{version:03d}.meta.json",
        {
            "chunk_id": chunk_id,
            "version": version,
            "duration": duration,
            "sha256": file_sha256(dest),
            "usage": usage,
            "instructions_hash": content_hash(instructions),
            "integrity": asdict(result),
            "promoted": False,
        },
    )
    if original.is_file() and original_sha:
        if file_sha256(original) != original_sha:
            raise IntegrityBlockedError("Retry must not overwrite the original chunk WAV.")
    return dest


def gate_master_promotion(results: list[TTSChunkIntegrityResult]) -> None:
    assert_promotable(results)
