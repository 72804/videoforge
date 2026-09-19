from __future__ import annotations

import json
import subprocess
from pathlib import Path

from docprod.render.ffmpeg import FFmpegError, ffmpeg_path, run_ffmpeg
from docprod.storage.hashing import file_sha256


def normalize_master_wav(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(tmp),
            ],
            timeout=120,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def measure_loudnorm(path: Path) -> dict[str, str]:
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    text = completed.stderr or ""
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def apply_loudnorm_wav(source: Path, dest: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Single-pass loudness normalize after concatenation. Returns (input, output) stats."""
    before = measure_loudnorm(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
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
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    after = measure_loudnorm(dest)
    return before, after


def mix_narration_stereo(wav: Path, dest: Path) -> dict[str, str]:
    stats = measure_loudnorm(wav)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(wav),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_fmts=fltp:"
                "sample_rates=48000:channel_layouts=stereo",
                str(tmp),
            ],
            timeout=120,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    stats["output_sha256"] = file_sha256(dest)
    return stats


def assert_audio_only_ok(path: Path) -> None:
    if not path.is_file():
        raise FFmpegError(f"Missing audio file {path}")
