from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docprod.render.ffmpeg import FFmpegError, ffmpeg_path, probe_media, run_ffmpeg

JOIN_SENTENCE = 0.24
JOIN_PARAGRAPH = 0.32
JOIN_CHAPTER = 0.36
MIN_JOIN = 0.18
MAX_JOIN_SENTENCE = 0.30
MAX_JOIN_CHAPTER = 0.45
EDGE_FADE = 0.008
SILENCE_NOISE = "-40dB"
SILENCE_MIN = 0.08


def join_target_seconds(boundary_type: str) -> float:
    if boundary_type in {"chapter"}:
        return JOIN_CHAPTER
    if boundary_type in {"paragraph"}:
        return JOIN_PARAGRAPH
    return JOIN_SENTENCE


def detect_edge_silence(path: Path) -> tuple[float | None, float | None]:
    """Return (leading, trailing) seconds if confidently detected, else None."""
    probe = probe_media(path)
    duration = probe.duration
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={SILENCE_NOISE}:d={SILENCE_MIN}",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    log = (completed.stderr or "") + (completed.stdout or "")
    starts = [float(item) for item in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(item) for item in re.findall(r"silence_end:\s*([0-9.]+)", log)]
    leading = None
    trailing = None
    if starts and ends and starts[0] <= 0.02:
        leading = max(0.0, min(ends[0], duration))
    if starts:
        last = starts[-1]
        if duration - last <= 0.08 or (ends and abs(ends[-1] - duration) <= 0.08):
            trailing = max(0.0, duration - last)
    return leading, trailing


def format_normalize_wav(source: Path, dest: Path) -> None:
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


def _write_silence(dest: Path, seconds: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            f"{max(seconds, 0.01):.4f}",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        timeout=30,
    )


def _trim_wav(source: Path, dest: Path, *, start: float, end: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fade = min(EDGE_FADE, max((end - start) / 8.0, 0.001))
    fade_out_at = max(end - start - fade, 0)
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-af",
            f"atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade:.4f},"
            f"afade=t=out:st={fade_out_at:.4f}:d={fade:.4f}",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        timeout=120,
    )


@dataclass(frozen=True)
class JoinResult:
    join_silences: list[float]
    part_durations: list[float]
    audio_windows: list[tuple[float, float]]


def concat_chunk_wavs(
    sources: list[Path],
    dest: Path,
    *,
    boundary_types: list[str],
) -> JoinResult:
    """Concat chunks with conservative internal join silence. No speech crossfade."""
    if not sources:
        raise FFmpegError("No narration chunks to concatenate")
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent / ".join_work"
    work.mkdir(parents=True, exist_ok=True)
    joins: list[float] = []
    parts: list[Path] = []
    part_durations: list[float] = []
    try:
        for index, source in enumerate(sources):
            probe = probe_media(source)
            leading, trailing = detect_edge_silence(source)
            start = 0.0
            end = probe.duration
            if index > 0 and leading is not None:
                start = min(leading, 0.35)
            if index < len(sources) - 1 and trailing is not None:
                end = max(start + 0.05, probe.duration - min(trailing, 0.45))
            trimmed = work / f"part_{index:03d}.wav"
            _trim_wav(source, trimmed, start=start, end=end)
            part_durations.append(probe_media(trimmed).duration)
            if index > 0:
                kind = boundary_types[index] if index < len(boundary_types) else "sentence"
                target = join_target_seconds(kind)
                if kind == "chapter":
                    target = min(max(target, MIN_JOIN), MAX_JOIN_CHAPTER)
                else:
                    target = min(max(target, MIN_JOIN), MAX_JOIN_SENTENCE)
                pad = work / f"join_{index:03d}.wav"
                _write_silence(pad, target)
                parts.append(pad)
                joins.append(round(target, 4))
            parts.append(trimmed)
        listing = work / "concat.txt"
        listing.write_text(
            "".join(f"file '{item.resolve().as_posix()}'\n" for item in parts),
            encoding="utf-8",
        )
        tmp = dest.with_suffix(".tmp.wav")
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(tmp)],
            timeout=180,
        )
        tmp.replace(dest)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
    windows: list[tuple[float, float]] = []
    cursor = 0.0
    for index, duration in enumerate(part_durations):
        if index > 0:
            cursor += joins[index - 1]
        windows.append((round(cursor, 4), round(cursor + duration, 4)))
        cursor += duration
    return JoinResult(
        join_silences=joins, part_durations=part_durations, audio_windows=windows
    )
