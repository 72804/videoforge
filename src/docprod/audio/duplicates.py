from __future__ import annotations

import math
import subprocess
from array import array
from dataclasses import dataclass
from pathlib import Path

from docprod.render.ffmpeg import ffmpeg_path


@dataclass
class DuplicateDetectionResult:
    path: str
    duration: float
    max_correlation: float
    repeated_span_seconds: float
    offset_seconds: float
    status: str
    reason: str


def _pcm_mono(path: Path, sample_rate: int = 4000) -> array:
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, timeout=120)
    if completed.returncode != 0:
        return array("h")
    samples = array("h")
    samples.frombytes(completed.stdout)
    return samples


def _envelope(samples: array, hop: int = 160) -> list[float]:
    values: list[float] = []
    for index in range(0, len(samples) - hop + 1, hop):
        window = samples[index : index + hop]
        values.append(math.sqrt(sum(item * item for item in window) / len(window)))
    return values


def _norm_corr(left: list[float], right: list[float]) -> float:
    if len(left) < 8 or len(left) != len(right):
        return 0.0
    mean_l = sum(left) / len(left)
    mean_r = sum(right) / len(right)
    num = sum((a - mean_l) * (b - mean_r) for a, b in zip(left, right, strict=True))
    den_l = math.sqrt(sum((a - mean_l) ** 2 for a in left))
    den_r = math.sqrt(sum((b - mean_r) ** 2 for b in right))
    if den_l < 1e-9 or den_r < 1e-9:
        return 0.0
    return num / (den_l * den_r)


def detect_repeated_audio(path: Path, *, sample_rate: int = 4000) -> DuplicateDetectionResult:
    """Lightweight envelope correlation. No transcription."""
    samples = _pcm_mono(path, sample_rate=sample_rate)
    duration = len(samples) / sample_rate if sample_rate else 0.0
    env = _envelope(samples)
    if len(env) < 20:
        return DuplicateDetectionResult(
            path=str(path),
            duration=duration,
            max_correlation=0.0,
            repeated_span_seconds=0.0,
            offset_seconds=0.0,
            status="INCONCLUSIVE",
            reason="audio too short for duplicate fingerprint",
        )
    best = 0.0
    best_off = 0
    best_span = 0
    window = max(len(env) // 3, 12)
    limit = len(env) - window
    probe = env[:window]
    step = max(1, window // 40)
    for offset in range(window // 2, limit + 1, step):
        score = _norm_corr(probe, env[offset : offset + window])
        if score > best:
            best = score
            best_off = offset
            best_span = window
    hop_seconds = 160 / sample_rate
    span = best_span * hop_seconds
    status = "PASS"
    reason = "no long repeated span"
    if best >= 0.85 and span >= max(8.0, duration * 0.28):
        status = "FAIL"
        reason = "long audio region strongly resembles an earlier region"
    elif best >= 0.72 and span >= 6.0:
        status = "SUSPICIOUS"
        reason = "possible restart or repeated tail"
    return DuplicateDetectionResult(
        path=str(path),
        duration=round(duration, 3),
        max_correlation=round(best, 4),
        repeated_span_seconds=round(span, 3),
        offset_seconds=round(best_off * hop_seconds, 3),
        status=status,
        reason=reason,
    )
